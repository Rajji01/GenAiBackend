package com.ticketing.inventory.dto;

import jakarta.validation.constraints.NotBlank;

public record ReleaseRequest(@NotBlank String holderId) {
}
