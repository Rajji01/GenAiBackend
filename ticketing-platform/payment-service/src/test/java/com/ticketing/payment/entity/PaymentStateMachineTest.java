package com.ticketing.payment.entity;

import org.junit.jupiter.api.Test;

import java.math.BigDecimal;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

// Pure unit tests for the Payment state machine — the "named transition
// methods gate every write" layer of the three-layer enforcement
// (WEEK3_DESIGN.md §1). No Spring, no DB, no Docker: the transition rules
// live entirely in the entity, so they're testable in isolation.
//
// Test-strategy note (Week 3 clean-pass): unlike Weeks 1–2 which used
// Testcontainers for everything, payment-service tests are deliberately
// pure JUnit/Mockito. Docker is fragile on this machine (AGENTS.md §7) and
// the invariants worth pinning here — transitions + orchestration — don't
// need a real Postgres to prove. Repository/DB-constraint behaviour is
// exercised live instead (Week 3 Day 4 evidence in PAYMENT_LAB.html).
class PaymentStateMachineTest {

    private Payment newInitiated() {
        return new Payment("sess-1", 1L, "user-1",
                new BigDecimal("100.00"), "INR", PaymentMethod.UPI);
    }

    @Test
    void freshPayment_startsInInitiated() {
        assertThat(newInitiated().getStatus()).isEqualTo(PaymentStatus.INITIATED);
    }

    @Test
    void markAuthorized_fromInitiated_movesToAuthorizedAndRecordsRefAndTimestamp() {
        Payment p = newInitiated();

        p.markAuthorized("gw-ref-1");

        assertThat(p.getStatus()).isEqualTo(PaymentStatus.AUTHORIZED);
        assertThat(p.getGatewayRef()).isEqualTo("gw-ref-1");
        assertThat(p.getAuthorizedAt()).isNotNull();
    }

    @Test
    void markAuthorized_twice_throws_becauseSecondCallIsNoLongerInitiated() {
        Payment p = newInitiated();
        p.markAuthorized("gw-ref-1");

        assertThatThrownBy(() -> p.markAuthorized("gw-ref-2"))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("markAuthorized requires status INITIATED");
    }

    @Test
    void markCaptured_fromAuthorized_movesToCapturedAndRecordsTimestamp() {
        Payment p = newInitiated();
        p.markAuthorized("gw-ref-1");

        p.markCaptured();

        assertThat(p.getStatus()).isEqualTo(PaymentStatus.CAPTURED);
        assertThat(p.getCapturedAt()).isNotNull();
    }

    @Test
    void markCaptured_fromInitiated_throws_captureRequiresAuthorized() {
        assertThatThrownBy(() -> newInitiated().markCaptured())
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("markCaptured requires status AUTHORIZED");
    }

    @Test
    void markFailed_fromInitiated_movesToFailed() {
        Payment p = newInitiated();

        p.markFailed("gateway declined");

        assertThat(p.getStatus()).isEqualTo(PaymentStatus.FAILED);
    }

    @Test
    void markFailed_fromAuthorized_movesToFailed_thisIsTheVoidPath() {
        Payment p = newInitiated();
        p.markAuthorized("gw-ref-1");

        p.markFailed("voided by caller");

        assertThat(p.getStatus()).isEqualTo(PaymentStatus.FAILED);
    }

    @Test
    void markFailed_fromCaptured_throws_captureMustGoThroughRefundNotFail() {
        Payment p = newInitiated();
        p.markAuthorized("gw-ref-1");
        p.markCaptured();

        // NOTE: CAPTURED is terminal, so the isTerminal() guard fires first and
        // the message reads "already CAPTURED" — the later "use refund path"
        // branch in markFailed() is therefore unreachable dead code. The
        // behaviour (a captured payment can't be failed, only refunded) is
        // correct; the hint text just never shows. Flagged for a future
        // cleanup pass — not touched here (Week 3 test pass writes tests over
        // the finished shape, doesn't refactor it).
        assertThatThrownBy(() -> p.markFailed("too late"))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("already CAPTURED");
    }

    @Test
    void markFailed_fromTerminalRefunded_throws() {
        Payment p = newInitiated();
        p.markAuthorized("gw-ref-1");
        p.markCaptured();
        p.markRefundPending();
        p.markRefunded();

        assertThatThrownBy(() -> p.markFailed("nope"))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("already");
    }

    @Test
    void markRefundPending_fromCaptured_movesToRefundPending() {
        Payment p = newInitiated();
        p.markAuthorized("gw-ref-1");
        p.markCaptured();

        p.markRefundPending();

        assertThat(p.getStatus()).isEqualTo(PaymentStatus.REFUND_PENDING);
    }

    @Test
    void markRefundPending_fromAuthorized_throws_refundNeedsCapturedFundsFirst() {
        Payment p = newInitiated();
        p.markAuthorized("gw-ref-1");

        assertThatThrownBy(p::markRefundPending)
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("markRefundPending requires status CAPTURED");
    }

    @Test
    void markRefunded_fromRefundPending_movesToRefundedAndRecordsTimestamp() {
        Payment p = newInitiated();
        p.markAuthorized("gw-ref-1");
        p.markCaptured();
        p.markRefundPending();

        p.markRefunded();

        assertThat(p.getStatus()).isEqualTo(PaymentStatus.REFUNDED);
        assertThat(p.getRefundedAt()).isNotNull();
    }

    @Test
    void isTerminal_isTrueOnlyForCapturedFailedAndRefunded() {
        assertThat(PaymentStatus.CAPTURED.isTerminal()).isTrue();
        assertThat(PaymentStatus.FAILED.isTerminal()).isTrue();
        assertThat(PaymentStatus.REFUNDED.isTerminal()).isTrue();

        assertThat(PaymentStatus.INITIATED.isTerminal()).isFalse();
        assertThat(PaymentStatus.AUTHORIZED.isTerminal()).isFalse();
        assertThat(PaymentStatus.REFUND_PENDING.isTerminal()).isFalse();
    }
}
