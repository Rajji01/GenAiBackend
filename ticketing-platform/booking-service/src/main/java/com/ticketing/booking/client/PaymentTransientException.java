package com.ticketing.booking.client;

// Retryable payment-service failure — 5xx, timeout, transport. Subclass
// so @Retry can target only these, mirroring the InventoryTransientException
// / InventoryClientException split that Bug 5's live fix left us with.
public class PaymentTransientException extends PaymentClientException {

    public PaymentTransientException(int statusCode, String message, Throwable cause) {
        super(statusCode, message, cause);
    }

    public PaymentTransientException(int statusCode, String message) {
        super(statusCode, message);
    }
}
