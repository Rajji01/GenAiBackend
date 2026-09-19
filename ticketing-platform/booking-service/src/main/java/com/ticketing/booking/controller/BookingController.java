package com.ticketing.booking.controller;

import com.ticketing.booking.dto.BookingRequest;
import com.ticketing.booking.dto.BookingResponse;
import com.ticketing.booking.service.BookingService;
import com.ticketing.booking.service.BookingService.BookingCreationResult;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/bookings")
@RequiredArgsConstructor
public class BookingController {

    private final BookingService bookingService;

    // Day 2: idempotency + persistence. Day 3 wires the saga; the same
    // endpoint keeps its shape (WEEK2_DESIGN.md §6) — until Day 3, every
    // fresh booking response comes back with status=PENDING.
    @PostMapping
    public ResponseEntity<BookingResponse> create(
            @RequestHeader("Idempotency-Key") String idempotencyKey,
            @Valid @RequestBody BookingRequest request) {
        BookingCreationResult result = bookingService.create(idempotencyKey, request);
        // 201 for a fresh booking, 200 for an idempotent retry of an existing
        // one. Both carry the SAME BookingResponse — the status code is the
        // only signal, on purpose. See WEEK2_DESIGN.md §6.
        HttpStatus status = result.freshlyCreated() ? HttpStatus.CREATED : HttpStatus.OK;
        return ResponseEntity.status(status).body(result.response());
    }

    @GetMapping("/{id}")
    public BookingResponse get(@PathVariable Long id) {
        return bookingService.get(id);
    }
}
