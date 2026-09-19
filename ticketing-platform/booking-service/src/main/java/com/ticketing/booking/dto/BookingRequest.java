package com.ticketing.booking.dto;

import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;
import jakarta.validation.constraints.Size;

import java.util.List;

// Client-facing request body. All validation is declarative here so the
// controller can rely on @Valid and never carries the "did the caller
// pass a valid X" checks in its head. See WEEK2_DESIGN.md §6.
public record BookingRequest(
        @NotNull @Positive Long showId,
        // Max 6 per WEEK2_DESIGN.md §6 — this is the real-world booking cap
        // (family/group of six is a natural upper bound; anything bigger is
        // a corporate booking flow, out of scope).
        @NotEmpty @Size(max = 6) List<@NotNull @Positive Long> seatIds,
        @NotBlank String holderId
) {
}
