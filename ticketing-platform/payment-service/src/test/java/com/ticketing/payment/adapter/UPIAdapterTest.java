package com.ticketing.payment.adapter;

import com.ticketing.payment.config.PaymentProperties;
import com.ticketing.payment.entity.PaymentMethod;
import com.ticketing.payment.exception.GatewayException;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.assertj.core.api.Assertions.assertThatCode;

// One concrete adapter's behaviour, incl. the simulate-failure knobs that
// Day 5 failure experiments rely on. The other two stubs (Card, NetBanking)
// share the same shape; this covers the Strategy contract + the failure
// switches without duplicating three near-identical files.
class UPIAdapterTest {

    private UPIAdapter adapter(boolean authFail, boolean captureFail) {
        return new UPIAdapter(new PaymentProperties(
                new PaymentProperties.Auth(1),
                new PaymentProperties.Simulate(authFail, captureFail)));
    }

    @Test
    void supports_reportsUPI() {
        assertThat(adapter(false, false).supports()).isEqualTo(PaymentMethod.UPI);
    }

    @Test
    void authorize_defaultKnobs_approvesWithAUpiPrefixedRef() {
        AuthResult result = adapter(false, false)
                .authorize(new BigDecimal("100.00"), "INR", "user-1");

        assertThat(result.approved()).isTrue();
        assertThat(result.gatewayRef()).startsWith("upi-");
        assertThat(result.declineReason()).isNull();
    }

    @Test
    void authorize_withSimulateAuthorizeFailure_declines() {
        AuthResult result = adapter(true, false)
                .authorize(new BigDecimal("100.00"), "INR", "user-1");

        assertThat(result.approved()).isFalse();
        assertThat(result.gatewayRef()).isNull();
        assertThat(result.declineReason()).contains("simulated UPI decline");
    }

    @Test
    void capture_withSimulateCaptureFailure_throwsGatewayException() {
        assertThatThrownBy(() -> adapter(false, true).capture("upi-ref"))
                .isInstanceOf(GatewayException.class)
                .hasMessageContaining("simulated UPI capture failure");
    }

    @Test
    void capture_defaultKnobs_succeeds() {
        assertThatCode(() -> adapter(false, false).capture("upi-ref"))
                .doesNotThrowAnyException();
    }
}
