package com.ticketing.payment.exception;

// Same pattern as booking-service: a paymentSessionKey reused with a
// different request body -> 422. See WEEK3_DESIGN.md §1 API contract.
public class IdempotencyKeyReuseException extends RuntimeException {
    public IdempotencyKeyReuseException(String message) { super(message); }
}
