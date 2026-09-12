package com.ufc.backend.dto;

import com.ufc.backend.entities.Bet;

public record BetResponse(
        Long betId,
        Long userId,
        Long fightId,
        Long fighterId,
        Double amount,
        Double odds,
        Bet.BetStatus status
) {
    public static BetResponse from(Bet bet) {
        return new BetResponse(
                bet.getBetId(),
                bet.getUser().getUserId(),
                bet.getFight().getFightId(),
                bet.getFighter().getFighterId(),
                bet.getAmount(),
                bet.getOdds(),
                bet.getStatus()
        );
    }
}
