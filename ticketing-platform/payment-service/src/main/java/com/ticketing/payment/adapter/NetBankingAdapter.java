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

// Net-banking stub. Real NB requires a bank redirect flow which our stub
// skips — the point is the adapter shape, not the redirect UX.
@Component
@RequiredArgsConstructor
public class NetBankingAdapter implements PaymentGateway {

    private static final Logger log = LoggerFactory.getLogger(NetBankingAdapter.class);

    private final PaymentProperties properties;

    @Override public PaymentMethod supports() { return PaymentMethod.NETBANKING; }

    @Override
    public AuthResult authorize(BigDecimal amount, String currency, String holderId) {
        if (properties.simulate().authorizeFailure()) {
            return AuthResult.declined("simulated NETBANKING decline");
        }
        String ref = "nb-" + UUID.randomUUID();
        log.info("nb_authorize_ok holder={} amount={} {} ref={}", holderId, amount, currency, ref);
        return AuthResult.approved(ref);
    }

    @Override
    public void capture(String gatewayRef) {
        if (properties.simulate().captureFailure()) {
            throw new GatewayException("simulated NETBANKING capture failure");
        }
        log.info("nb_capture_ok ref={}", gatewayRef);
    }

    @Override public void voidAuth(String gatewayRef) { log.info("nb_void_ok ref={}", gatewayRef); }
    @Override public void refund(String gatewayRef, BigDecimal amount, String reason) {
        log.info("nb_refund_ok ref={} amount={} reason={}", gatewayRef, amount, reason);
    }
}
