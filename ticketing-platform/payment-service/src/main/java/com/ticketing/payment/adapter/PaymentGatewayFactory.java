package com.ticketing.payment.adapter;

import com.ticketing.payment.entity.PaymentMethod;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;

import java.util.EnumMap;
import java.util.List;
import java.util.Map;

// Factory — resolves the right adapter for a given PaymentMethod. Spring
// injects every PaymentGateway bean (the three stubs); the factory indexes
// them by their supports() enum. Adding a new method + adapter is enough;
// the factory picks up the new bean automatically.
//
// Alternative would be a switch statement here, but that would require
// this class to know each concrete Adapter — the reverse of what DI is
// supposed to give us.
@Component
@RequiredArgsConstructor
public class PaymentGatewayFactory {

    private final List<PaymentGateway> gateways;
    private Map<PaymentMethod, PaymentGateway> byMethod;

    // Lazy-init to avoid ordering issues during context startup.
    private void ensureIndex() {
        if (byMethod == null) {
            byMethod = new EnumMap<>(PaymentMethod.class);
            for (PaymentGateway gw : gateways) {
                byMethod.put(gw.supports(), gw);
            }
        }
    }

    public PaymentGateway forMethod(PaymentMethod method) {
        ensureIndex();
        PaymentGateway gw = byMethod.get(method);
        if (gw == null) {
            throw new IllegalArgumentException(
                    "No gateway registered for method: " + method
                    + " (available: " + byMethod.keySet() + ")");
        }
        return gw;
    }
}
