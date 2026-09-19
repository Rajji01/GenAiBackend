package com.ticketing.payment.adapter;

import com.ticketing.payment.entity.PaymentMethod;

import java.math.BigDecimal;

// The Adapter contract — one interface, N gateway shapes.
//
// Deliberately narrow: authorize + capture + void + refund. Anything else
// a real gateway offers (recurring, subscriptions, split payments) is out
// of scope for this project. Adding a new payment method = write a new
// impl + add to Factory + add a case to the enum — compiler complains if
// any step is missed.
//
// Every method is idempotent by contract: calling twice with the same
// gatewayRef returns the same outcome. The stub impls model this
// explicitly; a real adapter would rely on the gateway's own
// idempotency-key semantics.
public interface PaymentGateway {

    PaymentMethod supports();

    AuthResult authorize(BigDecimal amount, String currency, String holderId);

    // Capture always succeeds against a stub — real gateways may fail
    // here too (auth expired, gateway maintenance) and Week 3's simulate-
    // capture-failure flag exercises that path.
    void capture(String gatewayRef);

    // Void an unused auth. Idempotent — voiding an already-voided or
    // already-captured auth is a no-op-with-existing-state.
    void voidAuth(String gatewayRef);

    // Refund a captured payment. Real gateways return "refund_id"; stubs
    // just complete.
    void refund(String gatewayRef, BigDecimal amount, String reason);
}
