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

// Card gateway stub. Real card auth uses 3-D Secure, PCI-scoped data,
// slower response times. Stub gives a distinct ref prefix so logs make
// clear which adapter served a payment.
@Component
@RequiredArgsConstructor
public class CardAdapter implements PaymentGateway {

    private static final Logger log = LoggerFactory.getLogger(CardAdapter.class);

    private final PaymentProperties properties;

    @Override public PaymentMethod supports() { return PaymentMethod.CARD; }

    @Override
    public AuthResult authorize(BigDecimal amount, String currency, String holderId) {
        if (properties.simulate().authorizeFailure()) {
            return AuthResult.declined("simulated CARD decline");
        }
        String ref = "card-" + UUID.randomUUID();
        log.info("card_authorize_ok holder={} amount={} {} ref={}", holderId, amount, currency, ref);
        return AuthResult.approved(ref);
    }

    @Override
    public void capture(String gatewayRef) {
        if (properties.simulate().captureFailure()) {
            throw new GatewayException("simulated CARD capture failure");
        }
        log.info("card_capture_ok ref={}", gatewayRef);
    }

    @Override
    public void voidAuth(String gatewayRef) {
        log.info("card_void_ok ref={}", gatewayRef);
    }

    @Override
    public void refund(String gatewayRef, BigDecimal amount, String reason) {
        log.info("card_refund_ok ref={} amount={} reason={}", gatewayRef, amount, reason);
    }
}
