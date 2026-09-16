package com.ticketing.inventory.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

// Typed, IDE-autocompletable config, bound from the `inventory.*` tree in
// application.yml. Deliberately scoped to just the hold TTL — the one
// config value actual business logic (HoldService) needs to read.
// Reconciliation's `enabled`/`interval-ms` stay as raw ${...} placeholders
// on @ConditionalOnProperty/@Scheduled instead of living here too: both
// of those are framework annotations evaluated before any
// @ConfigurationProperties bean exists to inject, so wrapping them in
// this class would just be a second, unused way to read the same
// property — indirection with no reader.
@ConfigurationProperties(prefix = "inventory")
public record InventoryProperties(Hold hold) {

    public record Hold(long ttlSeconds) {
    }
}
