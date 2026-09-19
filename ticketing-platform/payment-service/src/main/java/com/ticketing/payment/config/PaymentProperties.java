package com.ticketing.payment.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

// Typed config for payment-service. Auth window and simulate-failure knobs
// bound from payment.* keys in application.yml.
@ConfigurationProperties(prefix = "payment")
public record PaymentProperties(Auth auth, Simulate simulate) {

    public record Auth(int windowHours) {
        public Auth {
            if (windowHours <= 0) windowHours = 1;
        }
    }

    public record Simulate(boolean authorizeFailure, boolean captureFailure) {}
}
