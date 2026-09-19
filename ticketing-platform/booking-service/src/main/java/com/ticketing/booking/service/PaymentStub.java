package com.ticketing.booking.service;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import java.util.UUID;

// Stand-in for a real payment-service (Week 3 splits it out). Always
// returns success unless `booking.payment.simulate-failure=true` is set,
// which is exactly what Day 5's failure experiments will flip to prove
// the saga's rollback path against a real (in-process) failure source.
//
// A Strategy interface here would be over-abstraction today: there's ONE
// implementation and the "choose UPI vs Card vs NetBanking" concern belongs
// in payment-service, not booking. See ROADMAP.md §3 Phase 1 LLD note.
@Component
public class PaymentStub {

    private final boolean simulateFailure;

    public PaymentStub(@Value("${booking.payment.simulate-failure:false}") boolean simulateFailure) {
        this.simulateFailure = simulateFailure;
    }

    public PaymentResult charge(long bookingId, String holderId) {
        if (simulateFailure) {
            throw new PaymentFailedException(
                    "simulated payment failure for booking " + bookingId + " (holder " + holderId + ")");
        }
        return new PaymentResult("pay-stub-" + UUID.randomUUID());
    }

    public record PaymentResult(String paymentRef) {}

    public static class PaymentFailedException extends RuntimeException {
        public PaymentFailedException(String message) {
            super(message);
        }
    }
}
