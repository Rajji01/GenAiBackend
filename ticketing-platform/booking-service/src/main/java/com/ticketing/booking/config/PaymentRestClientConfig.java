package com.ticketing.booking.config;

import com.ticketing.booking.filter.CorrelationIdFilter;
import org.slf4j.MDC;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.web.client.RestClient;

// Sibling of InventoryRestClientConfig — same pattern, points at
// payment-service. Two separate @Bean RestClients so they can have
// independent timeouts (payment auth is slower than inventory hold).
@Configuration
public class PaymentRestClientConfig {

    @Bean
    RestClient paymentRestClient(BookingProperties properties) {
        int timeoutMs = (int) properties.payment().timeout().toMillis();
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(timeoutMs);
        factory.setReadTimeout(timeoutMs);

        return RestClient.builder()
                .baseUrl(properties.payment().baseUrl())
                .requestFactory(factory)
                .requestInterceptor((request, body, execution) -> {
                    String cid = MDC.get(CorrelationIdFilter.MDC_KEY);
                    if (cid != null) {
                        request.getHeaders().add(CorrelationIdFilter.HEADER, cid);
                    }
                    return execution.execute(request, body);
                })
                .build();
    }
}
