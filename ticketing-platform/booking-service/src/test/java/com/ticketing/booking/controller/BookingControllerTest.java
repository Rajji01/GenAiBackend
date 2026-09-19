package com.ticketing.booking.controller;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ticketing.booking.dto.BookingRequest;
import com.ticketing.booking.dto.BookingResponse;
import com.ticketing.booking.entity.BookingStatus;
import com.ticketing.booking.exception.IdempotencyKeyReuseException;
import com.ticketing.booking.exception.ResourceNotFoundException;
import com.ticketing.booking.service.BookingService;
import com.ticketing.booking.service.BookingService.BookingCreationResult;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.test.web.servlet.MockMvc;

import java.time.Instant;
import java.util.List;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.when;
import static org.springframework.http.MediaType.APPLICATION_JSON;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

// Controller slice — the HTTP contract, exception mapping, validation, and
// the 201-vs-200 status split. Service is mocked; DB and Redis stay out of
// the picture here, on purpose. Same pattern inventory-service uses.
@WebMvcTest(BookingController.class)
class BookingControllerTest {

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ObjectMapper objectMapper;

    @MockBean
    private BookingService bookingService;

    private BookingResponse responseWithStatus(BookingStatus status) {
        return new BookingResponse(101L, status, 1L, List.of(5L, 6L), "user-1",
                null, Instant.parse("2026-09-18T09:00:00Z"), null);
    }

    @Test
    void create_freshBooking_returns201_withPendingStatusOnDay2() throws Exception {
        when(bookingService.create(eq("key-A"), any(BookingRequest.class)))
                .thenReturn(new BookingCreationResult(responseWithStatus(BookingStatus.PENDING), true));

        mockMvc.perform(post("/bookings")
                        .header("Idempotency-Key", "key-A")
                        .contentType(APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(new BookingRequest(1L, List.of(5L, 6L), "user-1"))))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.bookingId").value(101))
                .andExpect(jsonPath("$.status").value("PENDING"));
    }

    @Test
    void create_idempotentRetry_returns200_withSameBody() throws Exception {
        when(bookingService.create(eq("key-A"), any(BookingRequest.class)))
                .thenReturn(new BookingCreationResult(responseWithStatus(BookingStatus.PENDING), false));

        mockMvc.perform(post("/bookings")
                        .header("Idempotency-Key", "key-A")
                        .contentType(APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(new BookingRequest(1L, List.of(5L, 6L), "user-1"))))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.bookingId").value(101));
    }

    @Test
    void create_withoutTheIdempotencyHeader_returns400() throws Exception {
        mockMvc.perform(post("/bookings")
                        .contentType(APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(new BookingRequest(1L, List.of(5L), "user-1"))))
                .andExpect(status().isBadRequest());
    }

    @Test
    void create_withInvalidBody_returns400_withFieldErrors() throws Exception {
        // Empty seatIds violates @NotEmpty
        mockMvc.perform(post("/bookings")
                        .header("Idempotency-Key", "key-invalid")
                        .contentType(APPLICATION_JSON)
                        .content("{\"showId\": 1, \"seatIds\": [], \"holderId\": \"user-1\"}"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.errors.seatIds").exists());
    }

    @Test
    void create_keyReuseWithDifferentBody_returns422() throws Exception {
        when(bookingService.create(eq("key-A"), any(BookingRequest.class)))
                .thenThrow(new IdempotencyKeyReuseException("Idempotency-Key 'key-A' was already used with a different request body"));

        mockMvc.perform(post("/bookings")
                        .header("Idempotency-Key", "key-A")
                        .contentType(APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(new BookingRequest(2L, List.of(1L), "user-2"))))
                .andExpect(status().isUnprocessableEntity());
    }

    @Test
    void get_existingBooking_returns200() throws Exception {
        when(bookingService.get(101L)).thenReturn(responseWithStatus(BookingStatus.PENDING));

        mockMvc.perform(get("/bookings/101"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.bookingId").value(101));
    }

    @Test
    void get_missingBooking_returns404() throws Exception {
        when(bookingService.get(999L)).thenThrow(new ResourceNotFoundException("Booking not found: 999"));

        mockMvc.perform(get("/bookings/999"))
                .andExpect(status().isNotFound());
    }
}
