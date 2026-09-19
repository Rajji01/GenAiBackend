package com.ticketing.booking.entity;

import jakarta.persistence.*;

import java.time.Instant;

// The booking aggregate. Owned entirely by booking-service — nothing else
// writes this row (WEEK2_DESIGN.md §2). Status transitions are gated by the
// three layers described in §1; on this class that means every state
// transition MUST go through a named method (markSeatsHeld, etc.), not a
// raw setStatus() — enforced by keeping status's setter package-private.
@Entity
@Table(
    name = "bookings",
    // Both indexes are the enforcement half of the idempotency scheme:
    // idempotency_key is unique globally (interview Q3 — dup key can only
    // mean one booking); the request_hash column sits alongside so a dup
    // key + a different body can be rejected as 422 rather than silently
    // returning the wrong booking.
    uniqueConstraints = @UniqueConstraint(name = "uk_bookings_idempotency_key", columnNames = "idempotency_key")
)
public class Booking {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "idempotency_key", nullable = false, length = 64)
    private String idempotencyKey;

    // SHA-256 of the canonical request body (see BookingService.canonicalHash).
    // Held on the row itself, not a separate table — the key IS the booking's
    // client-side identity, so its dedup evidence belongs with it.
    @Column(name = "request_hash", nullable = false, length = 64)
    private String requestHash;

    @Column(name = "show_id", nullable = false)
    private Long showId;

    @Column(name = "holder_id", nullable = false)
    private String holderId;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false)
    private BookingStatus status = BookingStatus.PENDING;

    // Populated when payment-service authorize returns. Nullable on
    // purpose: PENDING/SEATS_HELD/EXPIRED bookings genuinely have no
    // payment ref. Week 3: this now stores payment-service's paymentId
    // (formatted "pay-<id>"), and payment_id below stores the raw id for
    // recovery lookups.
    @Column(name = "payment_ref")
    private String paymentRef;

    // Week 3: paymentId from payment-service. Recovery sweep uses this
    // to GET /payments/{id} and resume mid-saga after a crash.
    @Column(name = "payment_id")
    private Long paymentId;

    // Week 3: captured-but-confirm-failed booking = refund needed. Auto-
    // refund is attempted immediately; if that fails (Resilience4j exhaust
    // on the refund call), booking stays FAILED with this flag true — ops
    // queue picks it up. See WEEK3_DESIGN.md §4 refund case.
    //
    // columnDefinition needed so Hibernate's ddl-auto: update can add
    // this column to an already-populated table (bug caught live
    // 2026-09-20: without the DEFAULT, Postgres refuses "NOT NULL column
    // with no default value" and the ALTER silently isn't emitted, then
    // Hibernate's own SELECT tries to read a column that doesn't exist).
    @Column(name = "refund_pending", nullable = false, columnDefinition = "BOOLEAN DEFAULT FALSE")
    private boolean refundPending = false;

    @Column(name = "created_at", nullable = false, updatable = false)
    private Instant createdAt;

    @Column(name = "confirmed_at")
    private Instant confirmedAt;

    // Same @Version pattern as inventory's Seat: a concurrent status
    // transition attempt loses the race cleanly instead of overwriting.
    @Version
    private Long version;

    protected Booking() {
        // JPA needs a no-arg constructor.
    }

    public Booking(String idempotencyKey, String requestHash, Long showId, String holderId) {
        this.idempotencyKey = idempotencyKey;
        this.requestHash = requestHash;
        this.showId = showId;
        this.holderId = holderId;
        this.status = BookingStatus.PENDING;
    }

    @PrePersist
    void assignCreatedAt() {
        this.createdAt = Instant.now();
    }

    // State transitions are the ONLY way to write `status`. Each one
    // validates the current state — a raw setStatus() would let a bug
    // silently move a terminal booking, which is exactly the class of
    // failure the three-layer enforcement in WEEK2_DESIGN.md §1 is
    // designed to prevent.

    public void markSeatsHeld() {
        expect(BookingStatus.PENDING, "markSeatsHeld");
        this.status = BookingStatus.SEATS_HELD;
    }

    public void markPaymentInitiated(Long paymentId, String paymentRef) {
        expect(BookingStatus.SEATS_HELD, "markPaymentInitiated");
        this.status = BookingStatus.PAYMENT_INITIATED;
        this.paymentId = paymentId;
        this.paymentRef = paymentRef;
    }

    public void markConfirmed() {
        expect(BookingStatus.PAYMENT_INITIATED, "markConfirmed");
        this.status = BookingStatus.CONFIRMED;
        this.confirmedAt = Instant.now();
    }

    public void markFailed() {
        if (status.isTerminal() && status != BookingStatus.FAILED) {
            throw new IllegalStateException(
                    "Cannot fail a booking that is already " + status + " (id=" + id + ")");
        }
        this.status = BookingStatus.FAILED;
    }

    // Week 3: FAILED but a refund is still owed. Distinct from plain
    // FAILED so ops queue can find it.
    public void markFailedRefundPending() {
        markFailed();
        this.refundPending = true;
    }

    // Called after ops (or the recovery sweep, once it re-drives a refund
    // successfully) processes the refund.
    public void clearRefundPending() {
        this.refundPending = false;
    }

    public void markExpired() {
        if (status.isTerminal()) {
            throw new IllegalStateException(
                    "Cannot expire a booking that is already " + status + " (id=" + id + ")");
        }
        this.status = BookingStatus.EXPIRED;
    }

    private void expect(BookingStatus required, String action) {
        if (status != required) {
            throw new IllegalStateException(
                    action + " requires status " + required + " but was " + status + " (id=" + id + ")");
        }
    }

    public Long getId() {
        return id;
    }

    public String getIdempotencyKey() {
        return idempotencyKey;
    }

    public String getRequestHash() {
        return requestHash;
    }

    public Long getShowId() {
        return showId;
    }

    public String getHolderId() {
        return holderId;
    }

    public BookingStatus getStatus() {
        return status;
    }

    public String getPaymentRef() {
        return paymentRef;
    }

    public Long getPaymentId() {
        return paymentId;
    }

    public boolean isRefundPending() {
        return refundPending;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }

    public Instant getConfirmedAt() {
        return confirmedAt;
    }

    public Long getVersion() {
        return version;
    }
}
