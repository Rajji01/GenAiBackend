package com.ticketing.booking.outbox;

import jakarta.persistence.*;

import java.time.Instant;

// One row per domain event to be published. Written in the SAME database
// transaction as the state change that produced it — this is what defeats
// the dual-write problem: either both the state change and the outbox
// row commit, or neither does. See WEEK3_DESIGN.md §3.
//
// A separate poller (OutboxPublisher) reads unpublished rows and delivers
// each to EventBus; on success it stamps published_at. Guarantee is
// at-least-once — consumers MUST be idempotent.
@Entity
@Table(
    name = "outbox_events",
    uniqueConstraints = @UniqueConstraint(name = "uk_outbox_event_id", columnNames = "event_id"),
    indexes = {
        @Index(name = "idx_outbox_unpublished", columnList = "published_at")
    }
)
public class OutboxEvent {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    // Week 3 Day 7 — stable event UUID. Generated once at record time,
    // travels through the payload to every consumer. Consumers dedupe on
    // this (unique constraint on their own end) — that's how the
    // "at-least-once outbox means consumers must be idempotent" contract
    // gets ENFORCED, not just documented. Without an event id, a
    // duplicated delivery (outbox publish succeeded but mark_published
    // failed → next poll re-publishes) would silently create duplicate
    // side-effects downstream.
    @Column(name = "event_id", nullable = false, length = 36, updatable = false)
    private String eventId;

    // The domain aggregate this event is about — booking id for
    // BookingConfirmed / BookingFailed etc. Useful for tracing.
    @Column(name = "aggregate_id", nullable = false, length = 64)
    private String aggregateId;

    // Event class name. Consumers switch on this.
    @Column(name = "event_type", nullable = false, length = 64)
    private String eventType;

    // Event body — JSON. Stored as text (not JSONB) so the entity stays
    // portable across DBs; parsing is done by the consumer side.
    @Column(nullable = false, columnDefinition = "TEXT")
    private String payload;

    @Column(name = "created_at", nullable = false, updatable = false)
    private Instant createdAt;

    // NULL until the publisher successfully hands off to EventBus.
    // Indexed WHERE published_at IS NULL for fast unpublished scan
    // (though we express this as a full index for JPA portability;
    // Postgres could use a partial index in a Flyway migration).
    @Column(name = "published_at")
    private Instant publishedAt;

    // Week 3 Day 6 addition — captured from MDC at record time so
    // the correlation id survives the @Scheduled thread boundary.
    // Without this the publisher (running in a scheduled thread with
    // an empty MDC) would drop the tracing context; downstreams got
    // correlation_id=null.
    @Column(name = "correlation_id", length = 64)
    private String correlationId;

    protected OutboxEvent() {} // JPA

    public OutboxEvent(String aggregateId, String eventType, String payload, String correlationId) {
        this.eventId = java.util.UUID.randomUUID().toString();
        this.aggregateId = aggregateId;
        this.eventType = eventType;
        this.payload = payload;
        this.correlationId = correlationId;
    }

    @PrePersist
    void assignCreatedAt() {
        this.createdAt = Instant.now();
    }

    public void markPublished() {
        this.publishedAt = Instant.now();
    }

    public Long getId() { return id; }
    public String getEventId() { return eventId; }
    public String getAggregateId() { return aggregateId; }
    public String getEventType() { return eventType; }
    public String getPayload() { return payload; }
    public Instant getCreatedAt() { return createdAt; }
    public Instant getPublishedAt() { return publishedAt; }
    public String getCorrelationId() { return correlationId; }
}
