package com.ticketing.booking.repository;

import com.ticketing.booking.entity.Booking;
import com.ticketing.booking.entity.BookingStatus;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;

import java.time.Instant;
import java.util.List;
import java.util.Optional;

public interface BookingRepository extends JpaRepository<Booking, Long> {

    // Idempotency check. Called before every insert; the unique index on
    // idempotency_key is the real guarantee, this lookup is the fast path
    // that returns the existing booking without touching the index.
    Optional<Booking> findByIdempotencyKey(String idempotencyKey);

    // Week 3: dangling-saga sweep candidates. Non-terminal bookings older
    // than the age filter (2 minutes) — this filter prevents racing an
    // in-flight saga (see WEEK3_DESIGN.md §5). Terminal statuses
    // (CONFIRMED, FAILED, EXPIRED) are excluded because they're done.
    @Query("SELECT b FROM Booking b " +
           "WHERE b.status IN (:statuses) " +
           "AND b.createdAt < :olderThan " +
           "ORDER BY b.id ASC")
    List<Booking> findDangling(List<BookingStatus> statuses, Instant olderThan);
}
