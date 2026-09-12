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
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@RequiredArgsConstructor
public class BetService {

    // Placeholder until a real odds engine exists — never let the client
    // supply its own odds, that would let a bettor guarantee their payout.
    private static final double PLACEHOLDER_ODDS = 1.91;

    private final BetRepository betRepository;
    private final UserRepository userRepository;
    private final FightRepository fightRepository;
    private final FighterRepository fighterRepository;

    @Transactional
    public BetResponse placeBet(BetRequest request) {
        User user = userRepository.findById(request.userId())
                .orElseThrow(() -> new ResourceNotFoundException("User not found: " + request.userId()));
        Fight fight = fightRepository.findById(request.fightId())
                .orElseThrow(() -> new ResourceNotFoundException("Fight not found: " + request.fightId()));
        Fighter fighter = fighterRepository.findById(request.fighterId())
                .orElseThrow(() -> new ResourceNotFoundException("Fighter not found: " + request.fighterId()));

        boolean fighterIsInThisFight = fighter.getFighterId().equals(fight.getFighter1().getFighterId())
                || fighter.getFighterId().equals(fight.getFighter2().getFighterId());
        if (!fighterIsInThisFight) {
            throw new InvalidRequestException(
                    "Fighter " + fighter.getFighterId() + " is not part of fight " + fight.getFightId());
        }

        Bet bet = Bet.builder()
                .user(user)
                .fight(fight)
                .fighter(fighter)
                .amount(request.amount())
                .odds(PLACEHOLDER_ODDS)
                .status(Bet.BetStatus.PENDING)
                .build();

        return BetResponse.from(betRepository.save(bet));
    }

    @Transactional
    public BetResponse updateBetAmount(Long betId, BetAmountUpdateRequest request) {
        Bet bet = betRepository.findById(betId)
                .orElseThrow(() -> new ResourceNotFoundException("Bet not found: " + betId));

        bet.setAmount(request.amount());
        // Hibernate includes `version` in the UPDATE ... WHERE clause. If
        // another request updated this same bet between our read and this
        // save, the row won't match and this throws
        // ObjectOptimisticLockingFailureException — handled globally as 409.
        return BetResponse.from(betRepository.save(bet));
    }
}
