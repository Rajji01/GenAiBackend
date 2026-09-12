package com.ufc.backend.controller;

import com.ufc.backend.dto.BetResponse;
import com.ufc.backend.entities.Bet;
import com.ufc.backend.exception.InvalidRequestException;
import com.ufc.backend.exception.ResourceNotFoundException;
import com.ufc.backend.service.BetService;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.dao.OptimisticLockingFailureException;
import org.springframework.http.MediaType;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.patch;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@WebMvcTest(BetController.class)
class BetControllerTest {

    @Autowired
    private MockMvc mockMvc;

    @MockitoBean
    private BetService betService;

    @Test
    void placeBet_withValidPayload_returns201() throws Exception {
        when(betService.placeBet(any()))
                .thenReturn(new BetResponse(1L, 1L, 100L, 10L, 50.0, 1.91, Bet.BetStatus.PENDING));

        mockMvc.perform(post("/bets")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"userId":1,"fightId":100,"fighterId":10,"amount":50.0}
                                """))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.betId").value(1))
                .andExpect(jsonPath("$.status").value("PENDING"));
    }

    @Test
    void placeBet_withMissingFields_returns400() throws Exception {
        mockMvc.perform(post("/bets")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{}"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.errors.userId").exists())
                .andExpect(jsonPath("$.errors.fightId").exists())
                .andExpect(jsonPath("$.errors.fighterId").exists())
                .andExpect(jsonPath("$.errors.amount").exists());
    }

    @Test
    void placeBet_whenFighterNotInFight_returns400WithDetail() throws Exception {
        when(betService.placeBet(any())).thenThrow(new InvalidRequestException("Fighter 99 is not part of fight 100"));

        mockMvc.perform(post("/bets")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"userId":1,"fightId":100,"fighterId":99,"amount":50.0}
                                """))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.detail").value("Fighter 99 is not part of fight 100"));
    }

    @Test
    void updateAmount_onUnknownBet_returns404() throws Exception {
        when(betService.updateBetAmount(eq(404L), any()))
                .thenThrow(new ResourceNotFoundException("Bet not found: 404"));

        mockMvc.perform(patch("/bets/404/amount")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"amount":75.0}
                                """))
                .andExpect(status().isNotFound());
    }

    @Test
    void updateAmount_whenConcurrentlyModified_returns409() throws Exception {
        when(betService.updateBetAmount(eq(1L), any()))
                .thenThrow(new OptimisticLockingFailureException("stale version"));

        mockMvc.perform(patch("/bets/1/amount")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"amount":75.0}
                                """))
                .andExpect(status().isConflict());
    }
}
