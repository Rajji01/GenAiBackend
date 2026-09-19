package com.ticketing.booking.service;

import com.ticketing.booking.client.InventoryClient;
import com.ticketing.booking.client.InventoryClientException;
import com.ticketing.booking.entity.Booking;
import com.ticketing.booking.entity.BookingSeat;
import com.ticketing.booking.entity.BookingStatus;
import com.ticketing.booking.repository.BookingRepository;
import com.ticketing.booking.repository.BookingSeatRepository;
import com.ticketing.booking.service.PaymentStub.PaymentFailedException;
import com.ticketing.booking.service.PaymentStub.PaymentResult;
import lombok.RequiredArgsConstructor;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.support.TransactionTemplate;

import java.time.Instant;
import java.util.ArrayList;
import java.util.List;

// The saga orchestrator. Given a PENDING booking, drives it through
// SEATS_HELD → PAYMENT_INITIATED → CONFIRMED, or handles the rollback if
// any step fails.
//
// Split from BookingService on purpose: idempotency/persistence and saga
// orchestration are genuinely different concerns. Idempotency answers
// "have I seen this request?" — a boundary concern. Saga answers "given
// the request is real, what's the state of the distributed workflow?" —
// a domain concern.
//
// Every state transition writes in its own transaction via
// TransactionTemplate — NOT @Transactional on private methods, which would
// silently bypass the Spring proxy on same-bean calls and run without a
// tx at all. Same class of fix as BookingService's REQUIRES_NEW insert
// (see Bug 3 in SAGA_LAB.html): explicit tx control beats invisible
// @Transactional semantics whenever the boundaries are non-obvious.
@Service
@RequiredArgsConstructor
public class BookingSagaService {

    private static final Logger log = LoggerFactory.getLogger(BookingSagaService.class);

    private final InventoryClient inventoryClient;
    private final PaymentStub paymentStub;
    private final BookingRepository bookingRepository;
    private final BookingSeatRepository bookingSeatRepository;
    private final PlatformTransactionManager txManager;

    public Booking runSaga(Long bookingId, Long showId, String holderId, List<Long> seatIds) {
        List<Long> heldSeats = new ArrayList<>();
        try {
            // Step 1: hold every seat via inventory. Loop, not batch — see
            // WEEK2_DESIGN.md §8 open question 3.
            for (Long seatId : seatIds) {
                var response = inventoryClient.hold(showId, seatId, holderId);
                heldSeats.add(seatId);
                writeTx().executeWithoutResult(status -> recordHoldToken(bookingId, seatId, response.holderId()));
            }
            writeTx().executeWithoutResult(status -> transitionToSeatsHeld(bookingId));

            // Step 2: charge. Payment stub for now; real payment-service Week 3.
            PaymentResult payment;
            try {
                payment = paymentStub.charge(bookingId, holderId);
            } catch (PaymentFailedException failure) {
                log.warn("saga_payment_failed bookingId={} reason={}", bookingId, failure.getMessage());
                compensateReleases(showId, holderId, bookingId, heldSeats);
                writeTx().executeWithoutResult(status -> markFailed(bookingId));
                throw new SagaFailedException(bookingId, "payment failed: " + failure.getMessage(), failure);
            }
            writeTx().executeWithoutResult(status ->
                    transitionToPaymentInitiated(bookingId, payment.paymentRef()));

            // Step 3: confirm every seat. If any confirm fails, we're in the
            // hard case: money moved, seat wasn't secured. Refund flag set
            // (real refund path arrives Week 3); this booking is FAILED but
            // recorded distinctly from a payment-fail so ops can act.
            for (Long seatId : seatIds) {
                inventoryClient.confirm(showId, seatId, holderId);
            }
            return writeTx().execute(status -> transitionToConfirmed(bookingId));

        } catch (InventoryClientException inventoryFail) {
            log.warn("saga_inventory_failed bookingId={} status={} reason={}",
                    bookingId, inventoryFail.getStatusCode(), inventoryFail.getMessage());
            compensateReleases(showId, holderId, bookingId, heldSeats);
            writeTx().executeWithoutResult(status -> markFailed(bookingId));
            throw new SagaFailedException(bookingId,
                    "inventory failure: " + inventoryFail.getMessage(), inventoryFail);
        }
    }

    // Best-effort compensation. Individual failures here are logged but
    // don't re-raise: hold TTL + reconciliation sweep in inventory-service
    // (Week 1) is the ultimate safety net for a release that couldn't be
    // delivered right now.
    private void compensateReleases(Long showId, String holderId, Long bookingId, List<Long> heldSeats) {
        for (Long seatId : heldSeats) {
            try {
                inventoryClient.release(showId, seatId, holderId);
                writeTx().executeWithoutResult(status -> markSeatReleased(bookingId, seatId));
            } catch (RuntimeException ex) {
                log.warn("saga_compensation_release_failed showId={} seatId={} reason={}",
                        showId, seatId, ex.getMessage());
            }
        }
    }

    // ---- Writes below run inside the TransactionTemplate-supplied tx ----

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

    private void transitionToPaymentInitiated(Long bookingId, String paymentRef) {
        Booking b = bookingRepository.findById(bookingId).orElseThrow();
        b.markPaymentInitiated(paymentRef);
        bookingRepository.save(b);
    }

    private Booking transitionToConfirmed(Long bookingId) {
        Booking b = bookingRepository.findById(bookingId).orElseThrow();
        b.markConfirmed();
        return bookingRepository.save(b);
    }

    private void markFailed(Long bookingId) {
        Booking b = bookingRepository.findById(bookingId).orElseThrow();
        if (b.getStatus() != BookingStatus.FAILED) {
            b.markFailed();
            bookingRepository.save(b);
        }
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

    // Thrown when the saga can't complete — the booking is persisted as
    // FAILED, and the controller maps this to 502 with a body containing
    // the bookingId so the client can GET /bookings/{id} for the details.
    public static class SagaFailedException extends RuntimeException {
        private final Long bookingId;

        public SagaFailedException(Long bookingId, String message, Throwable cause) {
            super(message, cause);
            this.bookingId = bookingId;
        }

        public Long getBookingId() {
            return bookingId;
        }
    }
}
