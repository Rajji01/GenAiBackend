package com.ticketing.inventory.dto;

import jakarta.validation.constraints.NotBlank;

// holderId stands in for an authenticated user/session id. There's no
// auth service in this project yet (that arrives with a real gateway,
// later phases) — for Week 1, whatever the caller sends here doubles as
// its own proof of ownership when releasing the same hold.
public record HoldRequest(@NotBlank String holderId) {
}
