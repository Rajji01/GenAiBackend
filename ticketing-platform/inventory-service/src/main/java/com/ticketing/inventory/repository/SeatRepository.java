package com.ticketing.inventory.repository;

import com.ticketing.inventory.entity.Seat;
import com.ticketing.inventory.entity.SeatStatus;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface SeatRepository extends JpaRepository<Seat, Long> {

    List<Seat> findByShowId(Long showId);

    // Used by HoldReconciliationService to find candidates for
    // TTL-expiry cleanup — every seat this returns is checked against
    // Redis, not assumed stale just for being HELD.
    List<Seat> findByStatus(SeatStatus status);
}
