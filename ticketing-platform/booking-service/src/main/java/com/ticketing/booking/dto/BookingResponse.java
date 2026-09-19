package com.ticketing.booking.dto;

import com.ticketing.booking.entity.Booking;
import com.ticketing.booking.entity.BookingSeat;
import com.ticketing.booking.entity.BookingStatus;

import java.time.Instant;
import java.util.List;

// The wire shape for a booking. `version` is deliberately omitted — same
// reasoning as SeatResponse in inventory-service (concurrency-control
// internal detail, not something a caller needs to see).
//
// `status` IS included: on Day 2, every booking is PENDING (saga arrives
// Day 3). On Day 3+, the caller can distinguish CONFIRMED from an
// intermediate state that a recovery sweep would move forward — see
// WEEK2_DESIGN.md §6.
public record BookingResponse(
        Long bookingId,
        BookingStatus status,
        Long showId,
        List<Long> seatIds,
        String holderId,
        String paymentRef,
        Instant createdAt,
        Instant confirmedAt
) {

    public static BookingResponse from(Booking booking, List<BookingSeat> seats) {
        List<Long> seatIds = seats.stream().map(BookingSeat::getSeatId).sorted().toList();
        return new BookingResponse(
                booking.getId(),
                booking.getStatus(),
                booking.getShowId(),
                seatIds,
                booking.getHolderId(),
                booking.getPaymentRef(),
                booking.getCreatedAt(),
                booking.getConfirmedAt()
        );
    }
}
