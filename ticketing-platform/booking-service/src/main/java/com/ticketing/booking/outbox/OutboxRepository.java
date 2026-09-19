package com.ticketing.booking.outbox;

import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;

import java.time.Instant;
import java.util.List;

public interface OutboxRepository extends JpaRepository<OutboxEvent, Long> {

    // Batched drain query. Order by id so publish order matches write order
    // (best effort — event ordering across aggregates isn't a guarantee here).
    @Query("SELECT e FROM OutboxEvent e WHERE e.publishedAt IS NULL ORDER BY e.id ASC")
    List<OutboxEvent> findUnpublished(Pageable pageable);

    // Called by the nightly retention job (not implemented Week 3, but
    // the query is here for the future prune).
    @Query("SELECT e FROM OutboxEvent e WHERE e.publishedAt IS NOT NULL AND e.publishedAt < :before")
    List<OutboxEvent> findPublishedBefore(Instant before, Pageable pageable);
}
