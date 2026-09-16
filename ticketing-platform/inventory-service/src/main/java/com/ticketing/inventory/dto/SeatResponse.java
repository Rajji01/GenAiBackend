package com.ticketing.inventory.dto;

import com.ticketing.inventory.entity.Seat;
import com.ticketing.inventory.entity.SeatStatus;

// The wire shape for a seat. Deliberately leaves out `version` — that's an
// internal concurrency-control detail for this service, not something a
// caller needs to see or send back.
public record SeatResponse(Long id, String seatNumber, SeatStatus status) {

    public static SeatResponse from(Seat seat) {
        return new SeatResponse(seat.getId(), seat.getSeatNumber(), seat.getStatus());
    }
}
