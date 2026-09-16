package com.ticketing.inventory.controller;

import com.ticketing.inventory.entity.Seat;
import com.ticketing.inventory.entity.SeatStatus;
import com.ticketing.inventory.service.SeatService;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.test.web.servlet.MockMvc;

import java.util.List;

import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

// @WebMvcTest loads only the web layer — SeatService is mocked, no real
// SeatRepository/database involved. This is why SeatSeedConfig lives in its
// own @Configuration class rather than as a @Bean on the application class:
// this slice would otherwise fail trying to construct a SeatRepository it
// has no datasource for.
@WebMvcTest(SeatController.class)
class SeatControllerTest {

    @Autowired
    private MockMvc mockMvc;

    @MockBean
    private SeatService seatService;

    @Test
    void availability_returnsSeatsAsJson_withoutLeakingVersion() throws Exception {
        Seat seat = new Seat(1L, "A1");
        when(seatService.getAvailability(1L)).thenReturn(List.of(seat));

        mockMvc.perform(get("/shows/1/seats/availability"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$[0].seatNumber").value("A1"))
                .andExpect(jsonPath("$[0].status").value("AVAILABLE"))
                .andExpect(jsonPath("$[0].version").doesNotExist());
    }

    @Test
    void availability_returnsEmptyArray_whenShowHasNoSeats() throws Exception {
        when(seatService.getAvailability(999L)).thenReturn(List.of());

        mockMvc.perform(get("/shows/999/seats/availability"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$").isArray())
                .andExpect(jsonPath("$").isEmpty());
    }
}
