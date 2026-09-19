package com.ticketing.payment.adapter;

import com.ticketing.payment.config.PaymentProperties;
import com.ticketing.payment.entity.PaymentMethod;
import com.ticketing.payment.exception.GatewayException;
import lombok.RequiredArgsConstructor;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;
import java.util.UUID;

// UPI gateway stub. Real UPI has instant confirmation but strict window
// semantics (30s auth expiry, e.g.); we don't simulate that timing here.
// Focus: return a deterministic gateway_ref, honor the simulate-failure
// knob so Day 5 experiments can force the auth-fail path.
@Component
@RequiredArgsConstructor
public class UPIAdapter implements PaymentGateway {

    private static final Logger log = LoggerFactory.getLogger(UPIAdapter.class);

    private final PaymentProperties properties;

    @Override
    public PaymentMethod supports() {
        return PaymentMethod.UPI;
    }

    @Override
    public AuthResult authorize(BigDecimal amount, String currency, String holderId) {
        if (properties.simulate().authorizeFailure()) {
            log.info("upi_authorize_simulated_failure holder={}", holderId);
            return AuthResult.declined("simulated UPI decline (payment.simulate.authorize-failure=true)");
        }
        String ref = "upi-" + UUID.randomUUID();
        log.info("upi_authorize_ok holder={} amount={} {} ref={}", holderId, amount, currency, ref);
        return AuthResult.approved(ref);
    }

    @Override
    public void capture(String gatewayRef) {
        if (properties.simulate().captureFailure()) {
            throw new GatewayException("simulated UPI capture failure (payment.simulate.capture-failure=true)");
        }
        log.info("upi_capture_ok ref={}", gatewayRef);
    }

    @Override
    public void voidAuth(String gatewayRef) {
        log.info("upi_void_ok ref={}", gatewayRef);
    }

    @Override
    public void refund(String gatewayRef, BigDecimal amount, String reason) {
        log.info("upi_refund_ok ref={} amount={} reason={}", gatewayRef, amount, reason);
    }
}
