package com.ticketing.inventory.entity;

import jakarta.persistence.*;

// One row per physical seat per show. showId is a foreign concept owned by
// catalog-service (Phase 2) — inventory-service doesn't validate it exists,
// it just tracks availability for whatever showId it's told about. The
// uniqueness constraint is the only integrity check that belongs here: two
// rows for the same seat on the same show would make "availability" itself
// ambiguous, which is a bug regardless of which service creates the row.
@Entity
@Table(
    name = "seats",
    uniqueConstraints = @UniqueConstraint(columnNames = {"show_id", "seat_number"})
)
public class Seat {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "show_id", nullable = false)
    private Long showId;

    @Column(name = "seat_number", nullable = false)
    private String seatNumber;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false)
    private SeatStatus status = SeatStatus.AVAILABLE;

    // Redis owns only the temporary hold. This durable owner makes a repeated
    // payment callback idempotent without letting another caller claim it.
    @Column(name = "booked_by_holder_id")
    private String bookedByHolderId;

    // The oversell-prevention mechanism for Day 3's hold/release. Hibernate
    // includes this in the WHERE clause of every UPDATE — a concurrent
    // writer that read the same row first will fail to update it, not
    // silently overwrite this one's change.
    @Version
    private Long version;

    protected Seat() {
        // JPA needs a no-arg constructor; not for application code to call.
    }

    public Seat(Long showId, String seatNumber) {
        this.showId = showId;
        this.seatNumber = seatNumber;
        this.status = SeatStatus.AVAILABLE;
    }

    public Long getId() {
        return id;
    }

    public Long getShowId() {
        return showId;
    }

    public String getSeatNumber() {
        return seatNumber;
    }

    public SeatStatus getStatus() {
        return status;
    }

    public void setStatus(SeatStatus status) {
        this.status = status;
    }

    public String getBookedByHolderId() {
        return bookedByHolderId;
    }

    public void setBookedByHolderId(String bookedByHolderId) {
        this.bookedByHolderId = bookedByHolderId;
    }

    public Long getVersion() {
        return version;
    }
}
