package com.ticketing.notification.entity;

import jakarta.persistence.*;

import java.time.Instant;

// One row per event received. Deliberately simple: we log + store
// everything, no aggregation, no de-dup (the consumer contract from
// the outbox pattern is "be idempotent" — so a real notification
// sender would check event_id here and skip duplicates; the stub
// just stores them all and prints).
//
// Deduplication is the ONE piece that would matter in prod. Week 3
// intentionally leaves it out so the at-least-once semantics of
// outbox are visible in the DB — if you see two rows for the same
// booking_id + event_type, you know the poller published twice.
@Entity
@Table(
    name = "notifications",
    // Week 3 Day 7 — unique constraint on event_id enforces the
    // "consumers must be idempotent" contract at DB level. Duplicate
    // delivery (outbox publish succeeded but mark_published failed →
    // poller re-publishes on next tick) hits this constraint and the
    // service catches it as a silent dedup, not a double-processed event.
    uniqueConstraints = @UniqueConstraint(name = "uk_notifications_event_id", columnNames = "event_id"),
    indexes = {
        @Index(name = "idx_notifications_holder", columnList = "holder_id"),
        @Index(name = "idx_notifications_booking", columnList = "booking_id")
    }
)
public class Notification {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    // Week 3 Day 7 — the producer's event_id (UUID). Unique constraint
    // (see @Table above) is the actual dedup mechanism; a second row
    // with the same event_id would throw DataIntegrityViolation.
    @Column(name = "event_id", nullable = false, length = 36, updatable = false)
    private String eventId;

    // The event type the producer sent. Booking-service currently sends
    // "BookingConfirmed" (and eventually BookingFailed, etc.).
    @Column(name = "event_type", nullable = false, length = 64)
    private String eventType;

    // Denormalized for query convenience — parsed out of the JSON payload
    // when the event lands. Nullable because not every event might carry
    // these (future events may be aggregate-level).
    @Column(name = "booking_id")
    private Long bookingId;

    @Column(name = "holder_id", length = 128)
    private String holderId;

    // Full raw JSON — kept as text so the event schema can evolve without
    // migrations. Real prod would validate against a schema registry.
    @Column(nullable = false, columnDefinition = "TEXT")
    private String payload;

    // Correlation id the producer sent — lets a booking's whole trace
    // include this consumer's actions too.
    @Column(name = "correlation_id", length = 64)
    private String correlationId;

    @Column(name = "received_at", nullable = false, updatable = false)
    private Instant receivedAt;

    protected Notification() {}

    public Notification(String eventId, String eventType, Long bookingId, String holderId,
                        String payload, String correlationId) {
        this.eventId = eventId;
        this.eventType = eventType;
        this.bookingId = bookingId;
        this.holderId = holderId;
        this.payload = payload;
        this.correlationId = correlationId;
    }

    @PrePersist
    void stamp() {
        this.receivedAt = Instant.now();
    }

    public Long getId() { return id; }
    public String getEventId() { return eventId; }
    public String getEventType() { return eventType; }
    public Long getBookingId() { return bookingId; }
    public String getHolderId() { return holderId; }
    public String getPayload() { return payload; }
    public String getCorrelationId() { return correlationId; }
    public Instant getReceivedAt() { return receivedAt; }
}
