package com.ticketing.booking.client;

// Any failure from the outgoing payment-service calls. Same shape as
// InventoryClientException — the saga catches this once and knows a
// compensating action is needed. Cause chain preserves the original.
public class PaymentClientException extends RuntimeException {

    private final int statusCode;

    public PaymentClientException(int statusCode, String message) {
        super(message);
        this.statusCode = statusCode;
    }

    public PaymentClientException(int statusCode, String message, Throwable cause) {
        super(message, cause);
        this.statusCode = statusCode;
    }

    // 0 = no HTTP response reached us (timeout, connect refused).
    public int getStatusCode() { return statusCode; }

    public boolean isConflict() { return statusCode == 409; }
    public boolean isBadGateway() { return statusCode == 502; }
}
