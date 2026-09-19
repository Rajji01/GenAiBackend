package com.ticketing.booking.exception;

// A dup Idempotency-Key with a DIFFERENT request body. Distinct from a
// conflict (409): the request itself is well-formed, it just contradicts an
// earlier request that already claimed the same key — RFC 9110 leaves this
// exact case ambiguous, and 422 Unprocessable Entity ("understood but semantic
// error") is the honest fit. See WEEK2_DESIGN.md §5.
public class IdempotencyKeyReuseException extends RuntimeException {
    public IdempotencyKeyReuseException(String message) {
        super(message);
    }
}
