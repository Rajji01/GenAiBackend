package com.ticketing.payment.entity;

// Full state machine per WEEK3_DESIGN.md §1. Every value is intentional;
// order matters because DB check constraint uses these names.
public enum PaymentStatus {
    INITIATED,         // row inserted, gateway call not yet made
    AUTHORIZED,        // gateway returned success; funds reserved
    CAPTURED,          // funds actually moved from customer → merchant  (terminal happy)
    FAILED,            // gateway declined / user cancelled / voided     (terminal)
    REFUND_PENDING,    // captured but downstream failed; refund flagged
    REFUNDED;          // refund actually processed                       (terminal)

    public boolean isTerminal() {
        return this == CAPTURED || this == FAILED || this == REFUNDED;
    }
}
