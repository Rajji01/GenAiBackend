package com.ticketing.booking.service;

import com.ticketing.booking.client.InventoryClient;
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
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.support.TransactionTemplate;

import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Map;

// Dangling-saga sweep. Picks up bookings whose saga crashed mid-flight
// and either drives them forward (if downstream state allows) or rolls
// them back cleanly. See WEEK3_DESIGN.md §5.
//
// Two-minute age filter is critical — never touches a booking younger
// than that, so we can't race an in-flight saga executing right now.
// Every operation this service invokes is idempotent by design, so
// re-driving is safe.
@Service
@RequiredArgsConstructor
public class BookingRecoveryService {

    private static final Logger log = LoggerFactory.getLogger(BookingRecoveryService.class);
    private static final Duration MIN_AGE = Duration.ofMinutes(2);

    private final BookingRepository bookingRepository;
    private final BookingSeatRepository seatRepository;
    private final InventoryClient inventoryClient;
    private final PaymentClient paymentClient;
    private final OutboxService outboxService;
    private final PlatformTransactionManager txManager;

    @Scheduled(fixedDelayString = "${booking.recovery.sweep-interval-ms:60000}")
    public void sweep() {
        Instant olderThan = Instant.now().minus(MIN_AGE);
        List<Booking> dangling = bookingRepository.findDangling(
                List.of(BookingStatus.PENDING, BookingStatus.SEATS_HELD, BookingStatus.PAYMENT_INITIATED),
                olderThan);
        if (dangling.isEmpty()) return;

        log.info("recovery_sweep found={} olderThan={}", dangling.size(), olderThan);
        for (Booking b : dangling) {
            try {
                recover(b);
            } catch (RuntimeException ex) {
                log.warn("recovery_failed bookingId={} status={} reason={}",
                        b.getId(), b.getStatus(), ex.getMessage());
            }
        }
    }

    void recover(Booking b) {
        log.info("recovery_start bookingId={} status={} createdAt={}",
                b.getId(), b.getStatus(), b.getCreatedAt());

        switch (b.getStatus()) {
            case PENDING -> {
                // Nothing was done — safe to fail immediately.
                writeTx().executeWithoutResult(s -> markFailed(b.getId()));
                log.info("recovery_pending_marked_failed bookingId={}", b.getId());
            }

            case SEATS_HELD -> recoverFromSeatsHeld(b);

            case PAYMENT_INITIATED -> recoverFromPaymentInitiated(b);

            default -> log.warn("recovery_unexpected_status bookingId={} status={}",
                    b.getId(), b.getStatus());
        }
    }

    private void recoverFromSeatsHeld(Booking b) {
        // Payment may or may not have started. We didn't record a
        // payment_id (that happens on transitionToPaymentInitiated),
        // but the paymentSessionKey is deterministic. Simplest safe
        // strategy: release seats + mark FAILED. If a payment DID
        // exist under the deterministic sessionKey, its own auth-expiry
        // sweep will void it eventually.
        //
        // A more optimistic recovery would query payment-service by
        // sessionKey and try to drive forward — omitted here to keep
        // recovery simple + safe. Next iteration could add.
        List<Long> heldSeats = seatIdsFor(b.getId());
        for (Long seatId : heldSeats) {
            tryRelease(b.getShowId(), seatId, b.getHolderId(), b.getId());
        }
        writeTx().executeWithoutResult(s -> markFailed(b.getId()));
        log.info("recovery_seats_held_rolled_back bookingId={} seats={}", b.getId(), heldSeats);
    }

    private void recoverFromPaymentInitiated(Booking b) {
        // We have a paymentId — query payment-service directly.
        Long paymentId = b.getPaymentId();
        if (paymentId == null) {
            log.warn("recovery_payment_initiated_no_payment_id bookingId={}", b.getId());
            // Same treatment as SEATS_HELD.
            recoverFromSeatsHeld(b);
            return;
        }

        PaymentClient.PaymentResponse payment;
        try {
            payment = paymentClient.getById(paymentId);
        } catch (PaymentClientException ex) {
            log.warn("recovery_payment_get_failed bookingId={} paymentId={} reason={}",
                    b.getId(), paymentId, ex.getMessage());
            return; // try next sweep
        }

        List<Long> allSeats = seatIdsFor(b.getId());

        switch (payment.status()) {
            case "FAILED" -> {
                // Payment already failed / voided → clean rollback.
                for (Long seatId : allSeats) tryRelease(b.getShowId(), seatId, b.getHolderId(), b.getId());
                writeTx().executeWithoutResult(s -> markFailed(b.getId()));
                log.info("recovery_payment_failed_rolled_back bookingId={}", b.getId());
            }
            case "AUTHORIZED" -> {
                // Auth done but capture never happened → capture then confirm.
                try {
                    paymentClient.capture(paymentId);
                    driveConfirms(b, allSeats, paymentId);
                } catch (RuntimeException ex) {
                    log.warn("recovery_capture_failed bookingId={} reason={}", b.getId(), ex.getMessage());
                }
            }
            case "CAPTURED" -> {
                // Money moved → confirm each seat; refund on failure.
                driveConfirms(b, allSeats, paymentId);
            }
            case "REFUND_PENDING", "REFUNDED" -> {
                // Already unwinding — just clean up.
                for (Long seatId : allSeats) tryRelease(b.getShowId(), seatId, b.getHolderId(), b.getId());
                writeTx().executeWithoutResult(s -> {
                    Booking cur = bookingRepository.findById(b.getId()).orElseThrow();
                    if (payment.status().equals("REFUNDED")) {
                        cur.markFailed();
                    } else {
                        cur.markFailedRefundPending();
                    }
                    bookingRepository.save(cur);
                });
                log.info("recovery_refund_state_finalized bookingId={} paymentStatus={}",
                        b.getId(), payment.status());
            }
            default -> log.warn("recovery_unknown_payment_status bookingId={} paymentStatus={}",
                    b.getId(), payment.status());
        }
    }

    private void driveConfirms(Booking b, List<Long> allSeats, Long paymentId) {
        for (Long seatId : allSeats) {
            try {
                inventoryClient.confirm(b.getShowId(), seatId, b.getHolderId());
            } catch (RuntimeException ex) {
                // Confirm failed after capture → refund + FAILED_REFUND_PENDING.
                log.warn("recovery_confirm_failed bookingId={} seatId={} reason={}",
                        b.getId(), seatId, ex.getMessage());
                boolean refundOk = tryRefund(paymentId, b.getId());
                for (Long s : allSeats) tryRelease(b.getShowId(), s, b.getHolderId(), b.getId());
                writeTx().executeWithoutResult(t -> {
                    if (refundOk) markFailed(b.getId()); else markFailedRefundPending(b.getId());
                });
                return;
            }
        }
        // All confirms OK — mark CONFIRMED + outbox event.
        writeTx().executeWithoutResult(s -> {
            Booking cur = bookingRepository.findById(b.getId()).orElseThrow();
            cur.markConfirmed();
            bookingRepository.save(cur);
            outboxService.record(String.valueOf(cur.getId()),
                    "BookingConfirmed",
                    Map.of(
                            "bookingId", cur.getId(),
                            "holderId", cur.getHolderId(),
                            "showId", cur.getShowId(),
                            "seatIds", allSeats,
                            "paymentId", paymentId,
                            "confirmedAt", Instant.now().toString(),
                            "recoveredBy", "recovery-sweep"
                    ));
        });
        log.info("recovery_confirmed bookingId={}", b.getId());
    }

    private void tryRelease(Long showId, Long seatId, String holderId, Long bookingId) {
        try {
            inventoryClient.release(showId, seatId, holderId);
            writeTx().executeWithoutResult(s -> markSeatReleased(bookingId, seatId));
        } catch (RuntimeException ex) {
            log.warn("recovery_release_failed showId={} seatId={} reason={}", showId, seatId, ex.getMessage());
        }
    }

    private boolean tryRefund(Long paymentId, Long bookingId) {
        try {
            paymentClient.refund(paymentId, "recovery refund for booking " + bookingId);
            return true;
        } catch (RuntimeException ex) {
            return false;
        }
    }

    private List<Long> seatIdsFor(Long bookingId) {
        return seatRepository.findByBookingId(bookingId).stream().map(BookingSeat::getSeatId).toList();
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
        for (BookingSeat bs : seatRepository.findByBookingId(bookingId)) {
            if (bs.getSeatId().equals(seatId)) {
                bs.setReleasedAt(Instant.now());
                seatRepository.save(bs);
            }
        }
    }

    private TransactionTemplate writeTx() {
        TransactionTemplate tx = new TransactionTemplate(txManager);
        tx.setPropagationBehavior(TransactionDefinition.PROPAGATION_REQUIRES_NEW);
        return tx;
    }
}
