package com.ticketing.payment.adapter;

import com.ticketing.payment.config.PaymentProperties;
import com.ticketing.payment.entity.PaymentMethod;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

// The Factory pattern's whole job: given a PaymentMethod, hand back the one
// adapter that supports() it — without the factory knowing any concrete
// adapter class. Spring would inject the real bean list; here we build the
// list by hand so the resolution logic is tested with zero context startup.
class PaymentGatewayFactoryTest {

    private static final PaymentProperties PROPS =
            new PaymentProperties(new PaymentProperties.Auth(1),
                    new PaymentProperties.Simulate(false, false));

    @Test
    void forMethod_resolvesEachMethodToTheAdapterThatSupportsIt() {
        PaymentGatewayFactory factory = new PaymentGatewayFactory(List.of(
                new UPIAdapter(PROPS), new CardAdapter(PROPS), new NetBankingAdapter(PROPS)));

        assertThat(factory.forMethod(PaymentMethod.UPI)).isInstanceOf(UPIAdapter.class);
        assertThat(factory.forMethod(PaymentMethod.CARD)).isInstanceOf(CardAdapter.class);
        assertThat(factory.forMethod(PaymentMethod.NETBANKING)).isInstanceOf(NetBankingAdapter.class);
    }

    @Test
    void forMethod_withNoAdapterRegisteredForThatMethod_throws() {
        // Only UPI wired — asking for NETBANKING must fail loudly, not
        // silently return null and NPE deeper in the flow.
        PaymentGatewayFactory factory =
                new PaymentGatewayFactory(List.of(new UPIAdapter(PROPS)));

        assertThatThrownBy(() -> factory.forMethod(PaymentMethod.NETBANKING))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("No gateway registered for method: NETBANKING");
    }
}
