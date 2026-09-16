package com.ticketing.inventory.exception;

// Distinct from ConflictException: a 409 means "the resource's state
// disagrees with what you assumed" (already held, already booked); a 403
// here means "the resource is fine, you're just not the one who holds it."
// Different failure, different retry advice for the caller.
public class ForbiddenException extends RuntimeException {
    public ForbiddenException(String message) {
        super(message);
    }
}
