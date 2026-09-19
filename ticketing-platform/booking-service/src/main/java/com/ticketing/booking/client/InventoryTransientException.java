package com.ticketing.booking.client;

// A subclass so @Retry can target only *this* type — the caller's catch
// on the parent InventoryClientException still works. Transient means
// "the same call, tried again in a moment, could reasonably succeed":
// 5xx from inventory, connect/read timeouts, connection refused. A 409
// (seat already held) is deliberately NOT transient — the same call will
// keep failing until real state changes, and retrying it just wastes the
// caller's latency budget while giving no chance of success.
public class InventoryTransientException extends InventoryClientException {

    public InventoryTransientException(int statusCode, String message, Throwable cause) {
        super(statusCode, message, cause);
    }

    public InventoryTransientException(int statusCode, String message) {
        super(statusCode, message);
    }
}
