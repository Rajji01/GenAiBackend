package com.ticketing.booking.client;

// Any failure from the outgoing inventory calls (HTTP error, timeout, IO,
// serialization). Kept as one type so the saga can `catch` in one place —
// it doesn't care WHY inventory failed, only that a compensating action is
// required. The cause chain preserves the original for logs.
public class InventoryClientException extends RuntimeException {

    private final int statusCode;

    public InventoryClientException(int statusCode, String message) {
        super(message);
        this.statusCode = statusCode;
    }

    public InventoryClientException(int statusCode, String message, Throwable cause) {
        super(message, cause);
        this.statusCode = statusCode;
    }

    // 0 = no HTTP response reached us (timeout, DNS, connection refused).
    public int getStatusCode() {
        return statusCode;
    }

    public boolean isConflict() {
        return statusCode == 409;
    }
}
