package com.ticketing.inventory.dto;

import jakarta.validation.constraints.NotBlank;

// Represents an already-successful payment callback. Payment processing stays
// outside inventory-service until that service boundary is introduced.
public record ConfirmRequest(@NotBlank String holderId) {
}
