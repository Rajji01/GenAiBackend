package com.ticketing.payment.entity;

// The three payment methods this project stubs. Extending the enum requires
// a matching adapter (see adapter/) plus a switch case in the factory —
// deliberate coupling so the compiler tells you what you missed.
public enum PaymentMethod {
    UPI,
    CARD,
    NETBANKING
}
