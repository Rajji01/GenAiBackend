package com.ticketing.booking.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

import java.time.Duration;

// Typed config for booking-service's outgoing HTTP + async concerns.
// Week 3 additions: payment (client base URL + timeout), outbox (poller
// interval + retention), recovery (dangling-saga sweep interval).
@ConfigurationProperties(prefix = "booking")
public record BookingProperties(
        Inventory inventory,
        Payment payment,
        Outbox outbox,
        Recovery recovery
) {

    public record Inventory(String baseUrl, Duration timeout) {
        public Inventory {
            if (baseUrl == null || baseUrl.isBlank()) baseUrl = "http://localhost:8081";
            if (timeout == null) timeout = Duration.ofSeconds(3);
        }
    }

    public record Payment(String baseUrl, Duration timeout) {
        public Payment {
            if (baseUrl == null || baseUrl.isBlank()) baseUrl = "http://localhost:8083";
            if (timeout == null) timeout = Duration.ofSeconds(5);
        }
    }

    public record Outbox(long pollIntervalMs, int retentionDays) {
        public Outbox {
            if (pollIntervalMs <= 0) pollIntervalMs = 2000;
            if (retentionDays <= 0) retentionDays = 30;
        }
    }

    public record Recovery(long sweepIntervalMs) {
        public Recovery {
            if (sweepIntervalMs <= 0) sweepIntervalMs = 60_000;
        }
    }
}
