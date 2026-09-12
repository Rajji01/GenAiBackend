package com.ufc.backend.service;

import com.ufc.backend.dto.BetAmountUpdateRequest;
import com.ufc.backend.dto.BetRequest;
import com.ufc.backend.dto.BetResponse;
import com.ufc.backend.entities.Bet;
import com.ufc.backend.entities.Fight;
import com.ufc.backend.entities.Fighter;
import com.ufc.backend.entities.User;
import com.ufc.backend.exception.InvalidRequestException;
import com.ufc.backend.exception.ResourceNotFoundException;
import com.ufc.backend.repository.BetRepository;
import com.ufc.backend.repository.FightRepository;
import com.ufc.backend.repository.FighterRepository;
import com.ufc.backend.repository.UserRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class BetServiceTest {

    @Mock private BetRepository betRepository;
    @Mock private UserRepository userRepository;
    @Mock private FightRepository fightRepository;
    @Mock private FighterRepository fighterRepository;

    private BetService betService;

    private User user;
    private Fighter fighter1;
    private Fighter fighter2;
    private Fighter fighterNotInFight;
    private Fight fight;

    @BeforeEach
    void setUp() {
        betService = new BetService(betRepository, userRepository, fightRepository, fighterRepository);

        user = User.builder().userId(1L).username("bettor_one").build();
        fighter1 = Fighter.builder().fighterId(10L).firstName("Alex").build();
        fighter2 = Fighter.builder().fighterId(20L).firstName("Israel").build();
        fighterNotInFight = Fighter.builder().fighterId(99L).firstName("Someone").build();
        fight = Fight.builder().fightId(100L).fighter1(fighter1).fighter2(fighter2).build();
    }

    @Test
    void placeBet_withFighterInTheFight_savesAndReturnsBet() {
        when(userRepository.findById(1L)).thenReturn(Optional.of(user));
        when(fightRepository.findById(100L)).thenReturn(Optional.of(fight));
        when(fighterRepository.findById(10L)).thenReturn(Optional.of(fighter1));
        when(betRepository.save(any(Bet.class))).thenAnswer(invocation -> {
            Bet bet = invocation.getArgument(0);
            bet.setBetId(500L);
            return bet;
        });

        BetResponse response = betService.placeBet(new BetRequest(1L, 100L, 10L, 50.0));

        assertThat(response.betId()).isEqualTo(500L);
        assertThat(response.fighterId()).isEqualTo(10L);
        assertThat(response.status()).isEqualTo(Bet.BetStatus.PENDING);
    }

    @Test
    void placeBet_withFighterNotInTheFight_throwsInvalidRequestException() {
        when(userRepository.findById(1L)).thenReturn(Optional.of(user));
        when(fightRepository.findById(100L)).thenReturn(Optional.of(fight));
        when(fighterRepository.findById(99L)).thenReturn(Optional.of(fighterNotInFight));

        assertThatThrownBy(() -> betService.placeBet(new BetRequest(1L, 100L, 99L, 50.0)))
                .isInstanceOf(InvalidRequestException.class)
                .hasMessageContaining("not part of fight");
    }

    @Test
    void placeBet_withUnknownFight_throwsResourceNotFoundException() {
        when(userRepository.findById(1L)).thenReturn(Optional.of(user));
        when(fightRepository.findById(999L)).thenReturn(Optional.empty());

        assertThatThrownBy(() -> betService.placeBet(new BetRequest(1L, 999L, 10L, 50.0)))
                .isInstanceOf(ResourceNotFoundException.class);
    }

    @Test
    void updateBetAmount_withUnknownBet_throwsResourceNotFoundException() {
        when(betRepository.findById(404L)).thenReturn(Optional.empty());

        assertThatThrownBy(() -> betService.updateBetAmount(404L, new BetAmountUpdateRequest(75.0)))
                .isInstanceOf(ResourceNotFoundException.class);
    }
}
