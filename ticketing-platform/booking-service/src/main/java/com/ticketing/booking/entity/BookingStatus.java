package com.ticketing.booking.entity;

// Every value here is intentional. See WEEK2_DESIGN.md §1 for the transition
// table and the three enforcement layers (entity method + DB check +
// @Version). Day 2 only sets PENDING; Day 3's saga populates the rest.
public enum BookingStatus {
    PENDING,
    SEATS_HELD,
    PAYMENT_INITIATED,
    CONFIRMED,
    FAILED,
    EXPIRED;

    public boolean isTerminal() {
        return this == CONFIRMED || this == FAILED || this == EXPIRED;
    }
}
