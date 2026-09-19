package com.ticketing.payment.exception;

// A gateway adapter reported failure. Distinct from PaymentNotFoundException
// or InvalidPaymentTransitionException so the caller (booking-service via
// its Resilience4j-wrapped client) can distinguish "you asked for a bad
// state transition" (don't retry) vs "the gateway had a bad time" (maybe
// retry).
public class GatewayException extends RuntimeException {
    public GatewayException(String message) { super(message); }
    public GatewayException(String message, Throwable cause) { super(message, cause); }
}
