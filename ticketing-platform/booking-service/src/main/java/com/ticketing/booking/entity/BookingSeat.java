package com.ticketing.booking.entity;

import jakarta.persistence.*;

import java.time.Instant;

// Bridge row per (booking, seat). Day 2 populates only booking_id + seat_id;
// hold_token is set when inventory /hold succeeds (Day 3), and released_at is
// set when compensation runs (Day 5). Living as a separate table now, not
// added later, so Day 3's schema stays additive (fill columns) rather than
// migratory (add tables). See WEEK2_DESIGN.md §8 open question 4.
@Entity
@Table(
    name = "booking_seats",
    uniqueConstraints = @UniqueConstraint(columnNames = {"booking_id", "seat_id"})
)
public class BookingSeat {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "booking_id", nullable = false)
    private Long bookingId;

    @Column(name = "seat_id", nullable = false)
    private Long seatId;

    // Filled by Day 3 once inventory /hold succeeds — nullable until then.
    // The bridge row's presence records "this booking wants this seat"; the
    // hold_token records "and this is the token that proves we've held it."
    @Column(name = "hold_token")
    private String holdToken;

    // Set when compensation releases the hold. Deliberately kept as an audit
    // trail rather than a hard delete — a failed booking's history is useful
    // for support/refund investigations (Week 3's refund path).
    @Column(name = "released_at")
    private Instant releasedAt;

    protected BookingSeat() {
        // JPA needs a no-arg constructor.
    }

    public BookingSeat(Long bookingId, Long seatId) {
        this.bookingId = bookingId;
        this.seatId = seatId;
    }

    public Long getId() {
        return id;
    }

    public Long getBookingId() {
        return bookingId;
    }

    public Long getSeatId() {
        return seatId;
    }

    public String getHoldToken() {
        return holdToken;
    }

    public void setHoldToken(String holdToken) {
        this.holdToken = holdToken;
    }

    public Instant getReleasedAt() {
        return releasedAt;
    }

    public void setReleasedAt(Instant releasedAt) {
        this.releasedAt = releasedAt;
    }
}
