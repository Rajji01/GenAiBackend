package com.ufc.backend.dto;

import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;

public record BetAmountUpdateRequest(
        @NotNull(message = "amount is required")
        @Positive(message = "amount must be greater than 0")
        Double amount
) {
}
