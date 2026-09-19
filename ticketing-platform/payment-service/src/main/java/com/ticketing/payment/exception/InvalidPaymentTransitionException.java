package com.ticketing.payment.exception;

// Wrap IllegalStateException from Payment's transition methods so the
// controller-advice layer maps it to a proper 409 with a client-safe body.
public class InvalidPaymentTransitionException extends RuntimeException {
    public InvalidPaymentTransitionException(String message) { super(message); }
    public InvalidPaymentTransitionException(String message, Throwable cause) { super(message, cause); }
}
