package com.ticketing.booking.service;

import com.ticketing.booking.client.InventoryClient;
import com.ticketing.booking.client.InventoryClientException;
import com.ticketing.booking.client.PaymentClient;
import com.ticketing.booking.client.PaymentClientException;
import com.ticketing.booking.entity.Booking;
import com.ticketing.booking.entity.BookingSeat;
import com.ticketing.booking.entity.BookingStatus;
import com.ticketing.booking.outbox.OutboxService;
import com.ticketing.booking.repository.BookingRepository;
import com.ticketing.booking.repository.BookingSeatRepository;
import lombok.RequiredArgsConstructor;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.support.TransactionTemplate;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

// Week 3 rewrite: PaymentStub → real PaymentClient (2-step authorize +
// capture) + outbox event on CONFIRMED + refund path when
// captured-but-confirm-fails.
//
// State progression:
//   PENDING → SEATS_HELD → PAYMENT_INITIATED → CONFIRMED (happy terminal)
//                                            ↓
//                                            FAILED
//                                            FAILED_REFUND_PENDING (captured but confirm failed)
//
// The @Retry / @CircuitBreaker on outgoing calls lives on the client
// classes (InventoryClient, PaymentClient); this service just calls them
// and translates their exceptions into saga rollback branches.
@Service
@RequiredArgsConstructor
public class BookingSagaService {

    private static final Logger log = LoggerFactory.getLogger(BookingSagaService.class);

    // Week 3 stub pricing — real pricing is a catalog/pricing service
    // concern (Phase 2). ₹500/seat, INR, UPI method. Configurable via
    // properties in a real deployment.
    private static final BigDecimal PRICE_PER_SEAT = BigDecimal.valueOf(500);
    private static final String CURRENCY = "INR";
    private static final String METHOD = "UPI";

    private final InventoryClient inventoryClient;
    private final PaymentClient paymentClient;
    private final BookingRepository bookingRepository;
    private final BookingSeatRepository bookingSeatRepository;
    private final OutboxService outboxService;
    private final PlatformTransactionManager txManager;

    public Booking runSaga(Long bookingId, Long showId, String holderId, List<Long> seatIds) {
        // Deterministic session key: same booking → same key → payment-
        // service returns the same payment on any retry.
        String idempotencyKey = writeTx().execute(status ->
                bookingRepository.findById(bookingId).orElseThrow().getIdempotencyKey());
        String paymentSessionKey = idempotencyKey + "-pay";
        BigDecimal amount = PRICE_PER_SEAT.multiply(BigDecimal.valueOf(seatIds.size()));

        List<Long> heldSeats = new ArrayList<>();

        try {
            // ---- Step 1: hold each seat ----
            for (Long seatId : seatIds) {
                var holdResp = inventoryClient.hold(showId, seatId, holderId);
                heldSeats.add(seatId);
                writeTx().executeWithoutResult(s -> recordHoldToken(bookingId, seatId, holdResp.holderId()));
            }
            writeTx().executeWithoutResult(s -> transitionToSeatsHeld(bookingId));

            // ---- Step 2: authorize payment ----
            PaymentClient.PaymentResponse auth;
            try {
                auth = paymentClient.authorize(new PaymentClient.AuthorizeRequest(
                        paymentSessionKey, bookingId, holderId, amount, CURRENCY, METHOD));
            } catch (PaymentClientException payFail) {
                log.warn("saga_payment_authorize_failed bookingId={} status={} reason={}",
                        bookingId, payFail.getStatusCode(), payFail.getMessage());
                compensateReleases(showId, holderId, bookingId, heldSeats);
                writeTx().executeWithoutResult(s -> markFailed(bookingId));
                throw new SagaFailedException(bookingId,
                        "payment authorize failed: " + payFail.getMessage(), payFail);
            }
            if (!"AUTHORIZED".equals(auth.status()) && !"CAPTURED".equals(auth.status())) {
                // Gateway declined (FAILED) or unexpected state
                log.warn("saga_payment_declined bookingId={} status={}", bookingId, auth.status());
                compensateReleases(showId, holderId, bookingId, heldSeats);
                writeTx().executeWithoutResult(s -> markFailed(bookingId));
                throw new SagaFailedException(bookingId,
                        "payment declined: status=" + auth.status(), null);
            }
            writeTx().executeWithoutResult(s -> transitionToPaymentInitiated(
                    bookingId, auth.paymentId(), "pay-" + auth.paymentId()));

            // ---- Step 3: capture (skip if already CAPTURED from a prior retry) ----
            if ("AUTHORIZED".equals(auth.status())) {
                try {
                    paymentClient.capture(auth.paymentId());
                } catch (PaymentClientException capFail) {
                    log.warn("saga_capture_failed bookingId={} paymentId={} reason={}",
                            bookingId, auth.paymentId(), capFail.getMessage());
                    // Void the auth (best-effort — funds not moved, no refund needed).
                    tryVoid(auth.paymentId());
                    compensateReleases(showId, holderId, bookingId, heldSeats);
                    writeTx().executeWithoutResult(s -> markFailed(bookingId));
                    throw new SagaFailedException(bookingId,
                            "payment capture failed: " + capFail.getMessage(), capFail);
                }
            }

            // ---- Step 4: confirm each seat ----
            for (Long seatId : seatIds) {
                try {
                    inventoryClient.confirm(showId, seatId, holderId);
                } catch (InventoryClientException confirmFail) {
                    // Money captured, seat can't be confirmed = REFUND path.
                    log.warn("saga_confirm_failed_after_capture bookingId={} seatId={} reason={}",
                            bookingId, seatId, confirmFail.getMessage());
                    boolean refundOk = tryRefund(auth.paymentId(), bookingId);
                    compensateReleases(showId, holderId, bookingId, heldSeats);
                    writeTx().executeWithoutResult(s -> {
                        if (refundOk) {
                            markFailed(bookingId);
                        } else {
                            markFailedRefundPending(bookingId);
                        }
                    });
                    throw new SagaFailedException(bookingId,
                            "confirm failed after capture (seat=" + seatId + "), refund "
                                    + (refundOk ? "ok" : "pending"), confirmFail);
                }
            }

            // ---- Step 5: mark CONFIRMED + write outbox event, SAME tx ----
            return writeTx().execute(s -> {
                Booking b = bookingRepository.findById(bookingId).orElseThrow();
                b.markConfirmed();
                Booking saved = bookingRepository.save(b);

                // Outbox: atomic with the state change. Poller drains this
                // and publishes to EventBus (stub → SNS in Phase 3).
                outboxService.record(
                        String.valueOf(bookingId),
                        "BookingConfirmed",
                        Map.of(
                                "bookingId", bookingId,
                                "holderId", holderId,
                                "showId", showId,
                                "seatIds", seatIds,
                                "paymentId", auth.paymentId(),
                                "confirmedAt", Instant.now().toString()
                        )
                );
                return saved;
            });

        } catch (InventoryClientException invFail) {
            log.warn("saga_inventory_failed bookingId={} status={} reason={}",
                    bookingId, invFail.getStatusCode(), invFail.getMessage());
            compensateReleases(showId, holderId, bookingId, heldSeats);
            writeTx().executeWithoutResult(s -> markFailed(bookingId));
            throw new SagaFailedException(bookingId,
                    "inventory failure: " + invFail.getMessage(), invFail);
        }
    }

    // ---- Compensations ----

    private void compensateReleases(Long showId, String holderId, Long bookingId, List<Long> heldSeats) {
        for (Long seatId : heldSeats) {
            try {
                inventoryClient.release(showId, seatId, holderId);
                writeTx().executeWithoutResult(s -> markSeatReleased(bookingId, seatId));
            } catch (RuntimeException ex) {
                log.warn("saga_release_compensation_failed showId={} seatId={} reason={}",
                        showId, seatId, ex.getMessage());
            }
        }
    }

    private void tryVoid(Long paymentId) {
        try {
            paymentClient.voidAuth(paymentId);
        } catch (RuntimeException ex) {
            log.warn("saga_void_failed paymentId={} reason={}", paymentId, ex.getMessage());
        }
    }

    private boolean tryRefund(Long paymentId, Long bookingId) {
        try {
            paymentClient.refund(paymentId, "booking " + bookingId + " confirm failed after capture");
            return true;
        } catch (RuntimeException ex) {
            log.warn("saga_refund_failed paymentId={} bookingId={} reason={}",
                    paymentId, bookingId, ex.getMessage());
            return false;
        }
    }

    // ---- DB writes (each in its own REQUIRES_NEW tx) ----

    private void recordHoldToken(Long bookingId, Long seatId, String holdToken) {
        bookingSeatRepository.findByBookingId(bookingId).stream()
                .filter(bs -> bs.getSeatId().equals(seatId))
                .findFirst()
                .ifPresent(bs -> {
                    bs.setHoldToken(holdToken);
                    bookingSeatRepository.save(bs);
                });
    }

    private void transitionToSeatsHeld(Long bookingId) {
        Booking b = bookingRepository.findById(bookingId).orElseThrow();
        b.markSeatsHeld();
        bookingRepository.save(b);
    }

    private void transitionToPaymentInitiated(Long bookingId, Long paymentId, String paymentRef) {
        Booking b = bookingRepository.findById(bookingId).orElseThrow();
        b.markPaymentInitiated(paymentId, paymentRef);
        bookingRepository.save(b);
    }

    private void markFailed(Long bookingId) {
        Booking b = bookingRepository.findById(bookingId).orElseThrow();
        if (b.getStatus() != BookingStatus.FAILED) {
            b.markFailed();
            bookingRepository.save(b);
        }
    }

    private void markFailedRefundPending(Long bookingId) {
        Booking b = bookingRepository.findById(bookingId).orElseThrow();
        b.markFailedRefundPending();
        bookingRepository.save(b);
    }

    private void markSeatReleased(Long bookingId, Long seatId) {
        for (BookingSeat bs : bookingSeatRepository.findByBookingId(bookingId)) {
            if (bs.getSeatId().equals(seatId)) {
                bs.setReleasedAt(Instant.now());
                bookingSeatRepository.save(bs);
            }
        }
    }

    private TransactionTemplate writeTx() {
        TransactionTemplate tx = new TransactionTemplate(txManager);
        tx.setPropagationBehavior(TransactionDefinition.PROPAGATION_REQUIRES_NEW);
        return tx;
    }

    public static class SagaFailedException extends RuntimeException {
        private final Long bookingId;

        public SagaFailedException(Long bookingId, String message, Throwable cause) {
            super(message, cause);
            this.bookingId = bookingId;
        }

        public Long getBookingId() { return bookingId; }
    }
}
