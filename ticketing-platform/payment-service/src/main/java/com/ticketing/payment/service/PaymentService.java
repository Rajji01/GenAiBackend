package com.ticketing.payment.service;

import com.ticketing.payment.adapter.AuthResult;
import com.ticketing.payment.adapter.PaymentGateway;
import com.ticketing.payment.adapter.PaymentGatewayFactory;
import com.ticketing.payment.config.PaymentProperties;
import com.ticketing.payment.dto.AuthorizeRequest;
import com.ticketing.payment.dto.PaymentResponse;
import com.ticketing.payment.entity.Payment;
import com.ticketing.payment.entity.PaymentStatus;
import com.ticketing.payment.exception.GatewayException;
import com.ticketing.payment.exception.IdempotencyKeyReuseException;
import com.ticketing.payment.exception.InvalidPaymentTransitionException;
import com.ticketing.payment.exception.PaymentNotFoundException;
import com.ticketing.payment.repository.PaymentRepository;
import lombok.RequiredArgsConstructor;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionTemplate;

import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Instant;
import java.util.HexFormat;
import java.util.List;

// The state-machine driver for payment. Every state change gates through
// Payment's named methods (three-layer enforcement); every write runs in
// its own tx via TransactionTemplate for the same reasons booking-service
// uses REQUIRES_NEW inserts — session poisoning after a constraint
// violation would otherwise break the fast-path idempotency lookup.
//
// This class does NOT know about @Retry / @CircuitBreaker — it calls the
// PaymentGateway adapter directly and translates gateway failures into
// GatewayException. The caller (booking-service via its PaymentClient)
// wraps those calls in its own Resilience4j policies.
@Service
@RequiredArgsConstructor
public class PaymentService {

    private static final Logger log = LoggerFactory.getLogger(PaymentService.class);

    private final PaymentRepository repo;
    private final PaymentGatewayFactory factory;
    private final PaymentProperties properties;
    private final PlatformTransactionManager txManager;

    public record CreationResult(PaymentResponse response, boolean freshlyCreated) {}

    // POST /payments — authorize path. Idempotent on paymentSessionKey.
    // Same-key + same-body → same payment returned (with whatever status
    // it currently has). Same-key + different-body → 422.
    public CreationResult authorize(AuthorizeRequest req) {
        String hash = canonicalHash(req);

        var existing = repo.findByPaymentSessionKey(req.paymentSessionKey());
        if (existing.isPresent()) {
            Payment p = existing.get();
            // Content-hash check via a comparison of amount + booking_id +
            // holder_id + method (the fields that could conflict). Distinct
            // from booking's approach which stores hash on the row; here
            // we recompute against the persisted values.
            if (!matchesBody(p, req)) {
                log.warn("payment_session_key_body_mismatch key={} paymentId={}",
                        req.paymentSessionKey(), p.getId());
                throw new IdempotencyKeyReuseException(
                        "paymentSessionKey '" + req.paymentSessionKey()
                        + "' was already used with a different request body");
            }
            log.info("payment_idempotent_retry key={} paymentId={} status={}",
                    req.paymentSessionKey(), p.getId(), p.getStatus());
            return new CreationResult(PaymentResponse.from(p), false);
        }

        // Insert + call gateway — insert in own tx so a race-loser can
        // cleanly re-read (same pattern as booking).
        Payment inserted;
        try {
            inserted = insertTx().execute(status -> {
                Payment fresh = new Payment(
                        req.paymentSessionKey(), req.bookingId(), req.holderId(),
                        req.amount(), req.currency(), req.method());
                return repo.saveAndFlush(fresh);
            });
        } catch (DataIntegrityViolationException race) {
            Payment winner = repo.findByPaymentSessionKey(req.paymentSessionKey())
                    .orElseThrow(() -> race);
            if (!matchesBody(winner, req)) {
                throw new IdempotencyKeyReuseException(
                        "paymentSessionKey '" + req.paymentSessionKey()
                        + "' was already used with a different request body");
            }
            log.info("payment_race_lost key={} paymentId={}",
                    req.paymentSessionKey(), winner.getId());
            return new CreationResult(PaymentResponse.from(winner), false);
        }

        // Call the gateway adapter (outside any tx — external call must not
        // hold a DB tx open).
        PaymentGateway gateway = factory.forMethod(req.method());
        AuthResult authResult;
        try {
            authResult = gateway.authorize(req.amount(), req.currency(), req.holderId());
        } catch (RuntimeException gatewayFailed) {
            // Gateway threw before returning a result — mark FAILED and
            // rethrow as GatewayException so caller knows.
            writeTx().executeWithoutResult(status -> markFailed(inserted.getId(),
                    "gateway threw: " + gatewayFailed.getMessage()));
            throw new GatewayException("authorize threw: " + gatewayFailed.getMessage(), gatewayFailed);
        }

        // Persist the result.
        Payment finalState;
        if (authResult.approved()) {
            finalState = writeTx().execute(status -> {
                Payment p = repo.findById(inserted.getId()).orElseThrow();
                p.markAuthorized(authResult.gatewayRef());
                return repo.save(p);
            });
            log.info("payment_authorized paymentId={} method={} gatewayRef={}",
                    finalState.getId(), req.method(), authResult.gatewayRef());
        } else {
            finalState = writeTx().execute(status -> {
                Payment p = repo.findById(inserted.getId()).orElseThrow();
                p.markFailed(authResult.declineReason());
                return repo.save(p);
            });
            log.info("payment_declined paymentId={} method={} reason={}",
                    finalState.getId(), req.method(), authResult.declineReason());
        }
        return new CreationResult(PaymentResponse.from(finalState), true);
    }

    // POST /payments/{id}/capture
    public PaymentResponse capture(Long id) {
        Payment p = getRequired(id);
        if (p.getStatus() == PaymentStatus.CAPTURED) {
            log.info("capture_idempotent_retry paymentId={}", id);
            return PaymentResponse.from(p);
        }
        if (p.getStatus() != PaymentStatus.AUTHORIZED) {
            throw new InvalidPaymentTransitionException(
                    "capture requires AUTHORIZED but was " + p.getStatus());
        }
        // Gateway call (outside tx).
        PaymentGateway gateway = factory.forMethod(p.getMethod());
        try {
            gateway.capture(p.getGatewayRef());
        } catch (RuntimeException ex) {
            throw new GatewayException("capture threw: " + ex.getMessage(), ex);
        }
        Payment final_ = writeTx().execute(status -> {
            Payment cur = repo.findById(id).orElseThrow();
            cur.markCaptured();
            return repo.save(cur);
        });
        log.info("payment_captured paymentId={} gatewayRef={}", id, final_.getGatewayRef());
        return PaymentResponse.from(final_);
    }

    // POST /payments/{id}/void — auth reversal for an unused authorization
    public PaymentResponse voidAuth(Long id) {
        Payment p = getRequired(id);
        if (p.getStatus() == PaymentStatus.FAILED) {
            log.info("void_idempotent_retry paymentId={}", id);
            return PaymentResponse.from(p);
        }
        if (p.getStatus() != PaymentStatus.AUTHORIZED) {
            throw new InvalidPaymentTransitionException(
                    "void requires AUTHORIZED but was " + p.getStatus());
        }
        try {
            factory.forMethod(p.getMethod()).voidAuth(p.getGatewayRef());
        } catch (RuntimeException ex) {
            throw new GatewayException("void threw: " + ex.getMessage(), ex);
        }
        Payment final_ = writeTx().execute(status -> {
            Payment cur = repo.findById(id).orElseThrow();
            try {
                cur.markFailed("voided by caller");
            } catch (IllegalStateException state) {
                throw new InvalidPaymentTransitionException(state.getMessage(), state);
            }
            return repo.save(cur);
        });
        log.info("payment_voided paymentId={}", id);
        return PaymentResponse.from(final_);
    }

    // POST /payments/{id}/refund — refund a captured payment
    public PaymentResponse refund(Long id, String reason) {
        Payment p = getRequired(id);
        if (p.getStatus() == PaymentStatus.REFUNDED
                || p.getStatus() == PaymentStatus.REFUND_PENDING) {
            log.info("refund_idempotent_retry paymentId={} status={}", id, p.getStatus());
            return PaymentResponse.from(p);
        }
        if (p.getStatus() != PaymentStatus.CAPTURED) {
            throw new InvalidPaymentTransitionException(
                    "refund requires CAPTURED but was " + p.getStatus());
        }
        // Move to REFUND_PENDING first (durable record we tried).
        Payment pending = writeTx().execute(status -> {
            Payment cur = repo.findById(id).orElseThrow();
            cur.markRefundPending();
            return repo.save(cur);
        });
        try {
            factory.forMethod(p.getMethod()).refund(p.getGatewayRef(), p.getAmount(), reason);
        } catch (RuntimeException ex) {
            // Refund gateway failed — leave at REFUND_PENDING, ops team
            // will retry manually. Do NOT flip back to CAPTURED — the
            // caller has already been told a refund is in flight.
            log.warn("refund_gateway_failed paymentId={} reason={}", id, ex.getMessage());
            throw new GatewayException("refund threw: " + ex.getMessage(), ex);
        }
        Payment final_ = writeTx().execute(status -> {
            Payment cur = repo.findById(id).orElseThrow();
            cur.markRefunded();
            return repo.save(cur);
        });
        log.info("payment_refunded paymentId={} reason={}", id, reason);
        return PaymentResponse.from(final_);
    }

    // GET /payments/{id}
    @Transactional(readOnly = true)
    public PaymentResponse get(Long id) {
        return PaymentResponse.from(getRequired(id));
    }

    // Called by AuthExpirySweep — void any AUTHORIZED payment older than
    // the configured window. Ops-invisible; log-only.
    void markFailed(Long id, String reason) {
        Payment p = repo.findById(id).orElseThrow();
        try {
            p.markFailed(reason);
            repo.save(p);
        } catch (IllegalStateException state) {
            log.warn("mark_failed_skip_terminal paymentId={} status={}", id, p.getStatus());
        }
    }

    private Payment getRequired(Long id) {
        return repo.findById(id).orElseThrow(
                () -> new PaymentNotFoundException("Payment not found: " + id));
    }

    private boolean matchesBody(Payment p, AuthorizeRequest req) {
        return p.getBookingId().equals(req.bookingId())
                && p.getHolderId().equals(req.holderId())
                && p.getAmount().compareTo(req.amount()) == 0
                && p.getCurrency().equals(req.currency())
                && p.getMethod() == req.method();
    }

    private TransactionTemplate insertTx() {
        TransactionTemplate tx = new TransactionTemplate(txManager);
        tx.setPropagationBehavior(TransactionDefinition.PROPAGATION_REQUIRES_NEW);
        return tx;
    }

    private TransactionTemplate writeTx() {
        TransactionTemplate tx = new TransactionTemplate(txManager);
        tx.setPropagationBehavior(TransactionDefinition.PROPAGATION_REQUIRES_NEW);
        return tx;
    }

    private static String canonicalHash(AuthorizeRequest req) {
        String canonical = req.bookingId() + "|" + req.holderId() + "|"
                + req.amount().toPlainString() + "|" + req.currency() + "|" + req.method();
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            return HexFormat.of().formatHex(digest.digest(canonical.getBytes()));
        } catch (NoSuchAlgorithmException impossible) {
            throw new IllegalStateException("SHA-256 unavailable", impossible);
        }
    }

    // ----- Auth expiry sweep -----

    // Utility used by AuthExpirySweepService (separate bean, easier to
    // test in isolation from the state machine).
    @Transactional(readOnly = true)
    public List<Long> findExpiredAuthorizations() {
        Instant threshold = Instant.now().minusSeconds(properties.auth().windowHours() * 3600L);
        return repo.findByStatusAndAuthorizedAtBefore(PaymentStatus.AUTHORIZED, threshold)
                .stream().map(Payment::getId).toList();
    }

    public void voidExpiredAuthorization(Long id) {
        try {
            voidAuth(id);
        } catch (RuntimeException ex) {
            log.warn("expiry_sweep_void_failed paymentId={} reason={}", id, ex.getMessage());
        }
    }
}
