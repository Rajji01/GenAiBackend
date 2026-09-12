package com.ufc.backend.dto;

import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;

// Note: odds is intentionally NOT client-supplied — letting a client dictate
// its own odds would be a real, exploitable production bug (guaranteed
// payouts). The server assigns a fixed placeholder odds value for now; a
// real odds engine is a separate, later concern.
public record BetRequest(
        @NotNull(message = "userId is required")
        Long userId,

        @NotNull(message = "fightId is required")
        Long fightId,

        @NotNull(message = "fighterId is required")
        Long fighterId,

        @NotNull(message = "amount is required")
        @Positive(message = "amount must be greater than 0")
        Double amount
) {
}
