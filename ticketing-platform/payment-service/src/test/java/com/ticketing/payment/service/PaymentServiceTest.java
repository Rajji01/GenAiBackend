package com.ticketing.payment.service;

import com.ticketing.payment.adapter.AuthResult;
import com.ticketing.payment.adapter.PaymentGateway;
import com.ticketing.payment.adapter.PaymentGatewayFactory;
import com.ticketing.payment.config.PaymentProperties;
import com.ticketing.payment.dto.AuthorizeRequest;
import com.ticketing.payment.dto.PaymentResponse;
import com.ticketing.payment.entity.Payment;
import com.ticketing.payment.entity.PaymentMethod;
import com.ticketing.payment.entity.PaymentStatus;
import com.ticketing.payment.exception.GatewayException;
import com.ticketing.payment.exception.IdempotencyKeyReuseException;
import com.ticketing.payment.exception.InvalidPaymentTransitionException;
import com.ticketing.payment.exception.PaymentNotFoundException;
import com.ticketing.payment.repository.PaymentRepository;
import com.ticketing.payment.service.PaymentService.CreationResult;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.transaction.PlatformTransactionManager;

import java.math.BigDecimal;
import java.util.Optional;
import java.util.concurrent.atomic.AtomicReference;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.*;

// Orchestration-level tests for PaymentService: idempotency, the auth →
// capture / void / refund lifecycle, gateway-failure translation, and the
// invalid-transition guards. All boundaries mocked (repo, factory, gateway,
// tx manager) so this is a fast, Docker-free unit test.
//
// Why a mocked PlatformTransactionManager works: TransactionTemplate.execute
// asks the manager for a status, runs the callback, then commits/rolls back.
// A Mockito mock returns a null status and no-ops commit/rollback, so the
// callback runs and its return value (or thrown exception) propagates exactly
// as it would against a real tx — which is all these tests assert on.
class PaymentServiceTest {

    private PaymentRepository repo;
    private PaymentGatewayFactory factory;
    private PaymentGateway gateway;
    private PlatformTransactionManager txManager;
    private PaymentService service;

    @BeforeEach
    void setUp() {
        repo = mock(PaymentRepository.class);
        factory = mock(PaymentGatewayFactory.class);
        gateway = mock(PaymentGateway.class);
        txManager = mock(PlatformTransactionManager.class);
        PaymentProperties properties = new PaymentProperties(
                new PaymentProperties.Auth(1), new PaymentProperties.Simulate(false, false));
        service = new PaymentService(repo, factory, properties, txManager);
        // Default: repo.save echoes its argument back (the state machine has
        // already mutated the entity in place before save is called).
        when(repo.save(any(Payment.class))).thenAnswer(inv -> inv.getArgument(0));
    }

    // ---- helpers ----

    private static void setId(Payment p, long id) {
        ReflectionTestUtils.setField(p, "id", id);
    }

    private AuthorizeRequest req(String key, PaymentMethod method) {
        return new AuthorizeRequest(key, 1L, "user-1", new BigDecimal("100.00"), "INR", method);
    }

    private Payment initiated(long id) {
        Payment p = new Payment("sess-" + id, 1L, "user-1",
                new BigDecimal("100.00"), "INR", PaymentMethod.UPI);
        setId(p, id);
        return p;
    }

    private Payment authorized(long id) {
        Payment p = initiated(id);
        p.markAuthorized("gw-" + id);
        return p;
    }

    private Payment captured(long id) {
        Payment p = authorized(id);
        p.markCaptured();
        return p;
    }

    // ---- authorize ----

    @Test
    void authorize_freshKeyGatewayApproves_insertsAndMovesToAuthorized() {
        String key = "k1";
        AtomicReference<Payment> inserted = new AtomicReference<>();
        when(repo.findByPaymentSessionKey(key)).thenReturn(Optional.empty());
        when(repo.saveAndFlush(any(Payment.class))).thenAnswer(inv -> {
            Payment p = inv.getArgument(0);
            setId(p, 1L);
            inserted.set(p);
            return p;
        });
        when(repo.findById(1L)).thenAnswer(inv -> Optional.of(inserted.get()));
        when(factory.forMethod(PaymentMethod.UPI)).thenReturn(gateway);
        when(gateway.authorize(any(), any(), any())).thenReturn(AuthResult.approved("gw-xyz"));

        CreationResult result = service.authorize(req(key, PaymentMethod.UPI));

        assertThat(result.freshlyCreated()).isTrue();
        assertThat(result.response().status()).isEqualTo(PaymentStatus.AUTHORIZED);
        assertThat(result.response().gatewayRef()).isEqualTo("gw-xyz");
        verify(gateway).authorize(any(), any(), any());
    }

    @Test
    void authorize_freshKeyGatewayDeclines_movesToFailed() {
        String key = "k2";
        AtomicReference<Payment> inserted = new AtomicReference<>();
        when(repo.findByPaymentSessionKey(key)).thenReturn(Optional.empty());
        when(repo.saveAndFlush(any(Payment.class))).thenAnswer(inv -> {
            Payment p = inv.getArgument(0);
            setId(p, 1L);
            inserted.set(p);
            return p;
        });
        when(repo.findById(1L)).thenAnswer(inv -> Optional.of(inserted.get()));
        when(factory.forMethod(PaymentMethod.UPI)).thenReturn(gateway);
        when(gateway.authorize(any(), any(), any())).thenReturn(AuthResult.declined("insufficient funds"));

        CreationResult result = service.authorize(req(key, PaymentMethod.UPI));

        assertThat(result.freshlyCreated()).isTrue();
        assertThat(result.response().status()).isEqualTo(PaymentStatus.FAILED);
    }

    @Test
    void authorize_gatewayThrows_marksFailedAndRethrowsAsGatewayException() {
        String key = "k3";
        AtomicReference<Payment> inserted = new AtomicReference<>();
        when(repo.findByPaymentSessionKey(key)).thenReturn(Optional.empty());
        when(repo.saveAndFlush(any(Payment.class))).thenAnswer(inv -> {
            Payment p = inv.getArgument(0);
            setId(p, 1L);
            inserted.set(p);
            return p;
        });
        when(repo.findById(1L)).thenAnswer(inv -> Optional.of(inserted.get()));
        when(factory.forMethod(PaymentMethod.UPI)).thenReturn(gateway);
        when(gateway.authorize(any(), any(), any())).thenThrow(new RuntimeException("gateway down"));

        assertThatThrownBy(() -> service.authorize(req(key, PaymentMethod.UPI)))
                .isInstanceOf(GatewayException.class);
        assertThat(inserted.get().getStatus()).isEqualTo(PaymentStatus.FAILED);
    }

    @Test
    void authorize_sameKeySameBody_returnsExistingWithoutCallingGateway() {
        String key = "k4";
        when(repo.findByPaymentSessionKey(key)).thenReturn(Optional.of(authorized(1L)));

        CreationResult result = service.authorize(req(key, PaymentMethod.UPI));

        assertThat(result.freshlyCreated()).isFalse();
        assertThat(result.response().paymentId()).isEqualTo(1L);
        verify(factory, never()).forMethod(any());
        verifyNoInteractions(gateway);
    }

    @Test
    void authorize_sameKeyDifferentBody_throws422() {
        String key = "k5";
        when(repo.findByPaymentSessionKey(key)).thenReturn(Optional.of(authorized(1L)));
        AuthorizeRequest differentAmount =
                new AuthorizeRequest(key, 1L, "user-1", new BigDecimal("999.00"), "INR", PaymentMethod.UPI);

        assertThatThrownBy(() -> service.authorize(differentAmount))
                .isInstanceOf(IdempotencyKeyReuseException.class);
        verifyNoInteractions(gateway);
    }

    // ---- capture ----

    @Test
    void capture_fromAuthorized_callsGatewayAndMovesToCaptured() {
        when(repo.findById(5L)).thenReturn(Optional.of(authorized(5L)));
        when(factory.forMethod(PaymentMethod.UPI)).thenReturn(gateway);

        PaymentResponse response = service.capture(5L);

        assertThat(response.status()).isEqualTo(PaymentStatus.CAPTURED);
        verify(gateway).capture("gw-5");
    }

    @Test
    void capture_alreadyCaptured_isIdempotentAndSkipsGateway() {
        when(repo.findById(6L)).thenReturn(Optional.of(captured(6L)));

        PaymentResponse response = service.capture(6L);

        assertThat(response.status()).isEqualTo(PaymentStatus.CAPTURED);
        verifyNoInteractions(gateway);
    }

    @Test
    void capture_fromInitiated_throwsInvalidTransition() {
        when(repo.findById(7L)).thenReturn(Optional.of(initiated(7L)));

        assertThatThrownBy(() -> service.capture(7L))
                .isInstanceOf(InvalidPaymentTransitionException.class);
    }

    // ---- refund ----

    @Test
    void refund_fromCaptured_movesThroughRefundPendingToRefunded() {
        when(repo.findById(8L)).thenReturn(Optional.of(captured(8L)));
        when(factory.forMethod(PaymentMethod.UPI)).thenReturn(gateway);

        PaymentResponse response = service.refund(8L, "user cancelled");

        assertThat(response.status()).isEqualTo(PaymentStatus.REFUNDED);
        verify(gateway).refund(eq("gw-8"), any(BigDecimal.class), eq("user cancelled"));
    }

    @Test
    void refund_alreadyRefunded_isIdempotentAndSkipsGateway() {
        Payment refunded = captured(9L);
        refunded.markRefundPending();
        refunded.markRefunded();
        when(repo.findById(9L)).thenReturn(Optional.of(refunded));

        PaymentResponse response = service.refund(9L, "again");

        assertThat(response.status()).isEqualTo(PaymentStatus.REFUNDED);
        verifyNoInteractions(gateway);
    }

    @Test
    void refund_fromAuthorized_throwsInvalidTransition() {
        when(repo.findById(10L)).thenReturn(Optional.of(authorized(10L)));

        assertThatThrownBy(() -> service.refund(10L, "x"))
                .isInstanceOf(InvalidPaymentTransitionException.class);
    }

    @Test
    void refund_gatewayFails_staysAtRefundPending_notFlippedBack() {
        Payment cap = captured(11L);
        when(repo.findById(11L)).thenReturn(Optional.of(cap));
        when(factory.forMethod(PaymentMethod.UPI)).thenReturn(gateway);
        doThrow(new RuntimeException("refund gateway down"))
                .when(gateway).refund(anyString(), any(BigDecimal.class), anyString());

        assertThatThrownBy(() -> service.refund(11L, "x"))
                .isInstanceOf(GatewayException.class);
        // The caller was already told a refund is in flight — must NOT revert
        // to CAPTURED nor jump to REFUNDED; ops retries from REFUND_PENDING.
        assertThat(cap.getStatus()).isEqualTo(PaymentStatus.REFUND_PENDING);
    }

    // ---- void ----

    @Test
    void voidAuth_fromAuthorized_callsGatewayAndMovesToFailed() {
        when(repo.findById(12L)).thenReturn(Optional.of(authorized(12L)));
        when(factory.forMethod(PaymentMethod.UPI)).thenReturn(gateway);

        PaymentResponse response = service.voidAuth(12L);

        assertThat(response.status()).isEqualTo(PaymentStatus.FAILED);
        verify(gateway).voidAuth("gw-12");
    }

    @Test
    void voidAuth_alreadyFailed_isIdempotentAndSkipsGateway() {
        Payment failed = initiated(13L);
        failed.markFailed("earlier decline");
        when(repo.findById(13L)).thenReturn(Optional.of(failed));

        PaymentResponse response = service.voidAuth(13L);

        assertThat(response.status()).isEqualTo(PaymentStatus.FAILED);
        verifyNoInteractions(gateway);
    }

    @Test
    void voidAuth_fromCaptured_throwsInvalidTransition() {
        when(repo.findById(14L)).thenReturn(Optional.of(captured(14L)));

        assertThatThrownBy(() -> service.voidAuth(14L))
                .isInstanceOf(InvalidPaymentTransitionException.class);
    }

    // ---- get ----

    @Test
    void get_missingId_throwsNotFound() {
        when(repo.findById(999L)).thenReturn(Optional.empty());

        assertThatThrownBy(() -> service.get(999L))
                .isInstanceOf(PaymentNotFoundException.class);
    }

    @Test
    void get_existingId_returnsResponse() {
        when(repo.findById(15L)).thenReturn(Optional.of(authorized(15L)));

        PaymentResponse response = service.get(15L);

        assertThat(response.paymentId()).isEqualTo(15L);
        assertThat(response.status()).isEqualTo(PaymentStatus.AUTHORIZED);
    }
}
