package com.ticketing.booking.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

import java.time.Duration;

// Typed config for the outgoing inventory calls (Day 3). Base URL is
// mandatory in real use; defaults here are the local docker-compose
// hostnames from inventory-service's own compose file. Timeout deliberately
// short — a slow inventory call blocks the caller for the whole flow, and
// a fast fail-fast + compensate is the right posture for a synchronous
// saga per WEEK2_DESIGN.md §6.
@ConfigurationProperties(prefix = "booking")
public record BookingProperties(Inventory inventory) {

    public record Inventory(String baseUrl, Duration timeout) {
        public Inventory {
            if (baseUrl == null || baseUrl.isBlank()) {
                baseUrl = "http://localhost:8081";
            }
            if (timeout == null) {
                timeout = Duration.ofSeconds(3);
            }
        }
    }
}
