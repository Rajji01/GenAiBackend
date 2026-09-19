package com.ticketing.booking.repository;

import com.ticketing.booking.entity.Booking;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Optional;

public interface BookingRepository extends JpaRepository<Booking, Long> {

    // Idempotency check. Called before every insert; the unique index on
    // idempotency_key is the real guarantee, this lookup is the fast path
    // that returns the existing booking without touching the index.
    Optional<Booking> findByIdempotencyKey(String idempotencyKey);
}
