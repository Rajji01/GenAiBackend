package com.ticketing.payment.adapter;

// Authorize result — the one thing every PaymentGateway.authorize()
// returns. Kept as a record so each adapter can only return one of these
// (a UPIAdapter returning a "UPIAuthResult" would leak the gateway's
// shape into payment-service's own domain).
public record AuthResult(String gatewayRef, boolean approved, String declineReason) {
    public static AuthResult approved(String gatewayRef) {
        return new AuthResult(gatewayRef, true, null);
    }
    public static AuthResult declined(String reason) {
        return new AuthResult(null, false, reason);
    }
}
