package com.ticketing.inventory.controller;

import com.ticketing.inventory.dto.HoldRequest;
import com.ticketing.inventory.dto.HoldResponse;
import com.ticketing.inventory.exception.ConflictException;
import com.ticketing.inventory.exception.ForbiddenException;
import com.ticketing.inventory.exception.ResourceNotFoundException;
import com.ticketing.inventory.service.HoldService;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.test.web.servlet.MockMvc;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.when;
import static org.springframework.http.MediaType.APPLICATION_JSON;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

// Proves the HTTP contract — status codes and the GlobalExceptionHandler
// wiring — without touching Redis or Postgres. The actual hold/release
// coordination logic is HoldServiceTest's job.
@WebMvcTest(HoldController.class)
class HoldControllerTest {

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ObjectMapper objectMapper;

    @MockBean
    private HoldService holdService;

    @Test
    void hold_withAValidRequest_returns200AndTheHoldResponse() throws Exception {
        when(holdService.hold(1L, 10L, "user-1")).thenReturn(new HoldResponse(10L, "user-1", 300));

        mockMvc.perform(post("/shows/1/seats/10/hold")
                        .contentType(APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(new HoldRequest("user-1"))))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.seatId").value(10))
                .andExpect(jsonPath("$.holderId").value("user-1"))
                .andExpect(jsonPath("$.ttlSeconds").value(300));
    }

    @Test
    void hold_withABlankHolderId_isRejectedBeforeReachingTheService() throws Exception {
        mockMvc.perform(post("/shows/1/seats/10/hold")
                        .contentType(APPLICATION_JSON)
                        .content("{\"holderId\": \"\"}"))
                .andExpect(status().isBadRequest());
    }

    @Test
    void hold_whenTheServiceReportsAConflict_returns409() throws Exception {
        when(holdService.hold(eq(1L), eq(10L), any()))
                .thenThrow(new ConflictException("Seat 10 is already held by someone else"));

        mockMvc.perform(post("/shows/1/seats/10/hold")
                        .contentType(APPLICATION_JSON)
                        .content("{\"holderId\": \"user-1\"}"))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.detail").value("Seat 10 is already held by someone else"));
    }

    @Test
    void hold_whenTheSeatDoesNotExist_returns404() throws Exception {
        when(holdService.hold(eq(1L), eq(999L), any()))
                .thenThrow(new ResourceNotFoundException("Seat not found: 999"));

        mockMvc.perform(post("/shows/1/seats/999/hold")
                        .contentType(APPLICATION_JSON)
                        .content("{\"holderId\": \"user-1\"}"))
                .andExpect(status().isNotFound());
    }

    @Test
    void release_withAValidRequest_returns204() throws Exception {
        mockMvc.perform(post("/shows/1/seats/10/release")
                        .contentType(APPLICATION_JSON)
                        .content("{\"holderId\": \"user-1\"}"))
                .andExpect(status().isNoContent());
    }

    @Test
    void release_byTheWrongHolder_returns403() throws Exception {
        doThrow(new ForbiddenException("holderId does not own the hold on seat 10"))
                .when(holdService).release(1L, 10L, "user-2");

        mockMvc.perform(post("/shows/1/seats/10/release")
                        .contentType(APPLICATION_JSON)
                        .content("{\"holderId\": \"user-2\"}"))
                .andExpect(status().isForbidden());
    }
}
