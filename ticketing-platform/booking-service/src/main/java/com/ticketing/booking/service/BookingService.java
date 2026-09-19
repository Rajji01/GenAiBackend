package com.ticketing.booking.service;

import com.ticketing.booking.dto.BookingRequest;
import com.ticketing.booking.dto.BookingResponse;
import com.ticketing.booking.entity.Booking;
import com.ticketing.booking.entity.BookingSeat;
import com.ticketing.booking.exception.IdempotencyKeyReuseException;
import com.ticketing.booking.exception.ResourceNotFoundException;
import com.ticketing.booking.repository.BookingRepository;
import com.ticketing.booking.repository.BookingSeatRepository;
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
import java.util.HexFormat;
import java.util.List;

// Day 2 scope: idempotency + persistence only. The saga (inventory /hold →
// payment → inventory /confirm) is Day 3 — every booking created today ends
// in PENDING on purpose and stays there. That state is what a recovery sweep
// on Day 5 would eventually pick up; the point today is to prove the
// idempotency contract in isolation before adding a distributed workflow on
// top of it.
//
// Why the insert step lives in its OWN transaction (see `insertTx`):
// two parallel creates for the same fresh key both pass the initial lookup,
// both try to insert, one loses the unique-index race. If both inserts
// shared the caller's transaction, catching the DataIntegrityViolationException
// wouldn't be safe — Hibernate marks the session poisoned ("don't flush the
// Session after an exception occurs") and any follow-up read blows up. A
// REQUIRES_NEW insert isolates the failure to a self-contained rollback so
// the outer flow can cleanly re-read and return the winning row.
@Service
@RequiredArgsConstructor
public class BookingService {

    private static final Logger log = LoggerFactory.getLogger(BookingService.class);

    private final BookingRepository bookingRepository;
    private final BookingSeatRepository bookingSeatRepository;
    private final BookingSagaService sagaService;
    private final PlatformTransactionManager txManager;

    // Result carrier so the controller can distinguish "new" (201) from
    // "retry of existing" (200) without a second DB round-trip.
    public record BookingCreationResult(BookingResponse response, boolean freshlyCreated) {}

    public BookingCreationResult create(String idempotencyKey, BookingRequest request) {
        String hash = canonicalHash(request);

        // Fast path: an existing booking under this key. Do NOT re-run the
        // saga for an idempotent retry — whatever the booking's current
        // status is (CONFIRMED, FAILED, or still mid-flight), that's the
        // authoritative answer. Re-running the saga would compound charges
        // or double-hold seats. This is the entire point of idempotency
        // being enforced at the boundary before any side-effect fires.
        var existing = bookingRepository.findByIdempotencyKey(idempotencyKey);
        if (existing.isPresent()) {
            return matchOrThrow(existing.get(), hash, idempotencyKey, false, "booking_idempotent_retry");
        }

        // Slow path: try to insert PENDING in an independent transaction
        // (see class comment). Race → catch → re-read in another fresh read.
        Booking pending;
        try {
            pending = insertTx().execute(status -> insertNew(idempotencyKey, hash, request));
            log.info("booking_created key={} bookingId={} status=PENDING", idempotencyKey, pending.getId());
        } catch (DataIntegrityViolationException race) {
            Booking winner = bookingRepository.findByIdempotencyKey(idempotencyKey)
                    .orElseThrow(() -> race);
            // Race loser: don't re-run the saga either — the winner is
            // already driving it (or done). Return the winner's current state.
            return matchOrThrow(winner, hash, idempotencyKey, false, "booking_idempotent_race_lost");
        }

        // Saga runs OUTSIDE the insert's transaction on purpose. The PENDING
        // row must be durably committed before any downstream call fires —
        // otherwise a crash after e.g. /hold but before commit would leave a
        // held seat with no booking record to compensate against. See
        // WEEK2_DESIGN.md §7 sequence diagrams.
        Booking finalState = sagaService.runSaga(
                pending.getId(), request.showId(), request.holderId(), request.seatIds());

        return new BookingCreationResult(toResponse(finalState), true);
    }

    private BookingCreationResult matchOrThrow(Booking existing, String hash, String key, boolean fresh, String logEvent) {
        if (!existing.getRequestHash().equals(hash)) {
            log.warn("idempotency_key_reuse_body_mismatch key={} bookingId={}", key, existing.getId());
            throw new IdempotencyKeyReuseException(
                    "Idempotency-Key '" + key + "' was already used with a different request body");
        }
        log.info("{} key={} bookingId={}", logEvent, key, existing.getId());
        return new BookingCreationResult(toResponse(existing), fresh);
    }

    private Booking insertNew(String idempotencyKey, String hash, BookingRequest request) {
        // saveAndFlush, not save: force the INSERT to happen NOW so a unique-
        // index violation is thrown here and caught by the outer catch — not
        // deferred to commit-time where it would tangle with the transaction
        // completion.
        Booking booking = bookingRepository.saveAndFlush(
                new Booking(idempotencyKey, hash, request.showId(), request.holderId()));
        for (Long seatId : request.seatIds()) {
            bookingSeatRepository.save(new BookingSeat(booking.getId(), seatId));
        }
        return booking;
    }

    private TransactionTemplate insertTx() {
        TransactionTemplate tx = new TransactionTemplate(txManager);
        tx.setPropagationBehavior(TransactionDefinition.PROPAGATION_REQUIRES_NEW);
        return tx;
    }

    @Transactional(readOnly = true)
    public BookingResponse get(Long id) {
        Booking booking = bookingRepository.findById(id)
                .orElseThrow(() -> new ResourceNotFoundException("Booking not found: " + id));
        return toResponse(booking);
    }

    private BookingResponse toResponse(Booking booking) {
        List<BookingSeat> seats = bookingSeatRepository.findByBookingId(booking.getId());
        return BookingResponse.from(booking, seats);
    }

    // Canonical form: order-independent for seatIds so a client that reorders
    // the same seats doesn't accidentally trip the 422 branch. SHA-256 is
    // overkill for collision odds but cheap; it's the same primitive the
    // rest of the stack (JWT, TLS) already needs, so no new dependency.
    static String canonicalHash(BookingRequest request) {
        List<Long> sortedSeats = request.seatIds().stream().sorted().toList();
        String canonical = request.showId() + "|" + sortedSeats + "|" + request.holderId();
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            return HexFormat.of().formatHex(digest.digest(canonical.getBytes()));
        } catch (NoSuchAlgorithmException impossible) {
            throw new IllegalStateException("SHA-256 unavailable", impossible);
        }
    }
}
