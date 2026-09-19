package com.ticketing.booking.config;

import com.ticketing.booking.filter.CorrelationIdFilter;
import org.slf4j.MDC;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.web.client.RestClient;

// Splits RestClient construction out of InventoryClient so tests can bind
// MockRestServiceServer to the client instead of standing up a real HTTP
// server. Was inlined into InventoryClient originally; the split appeared
// the moment the first Resilience4j test needed a mock-server-backed
// RestClient. See BookingProperties for the base URL + timeout knobs.
@Configuration
public class InventoryRestClientConfig {

    @Bean
    RestClient inventoryRestClient(BookingProperties properties) {
        int timeoutMs = (int) properties.inventory().timeout().toMillis();
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(timeoutMs);
        factory.setReadTimeout(timeoutMs);

        return RestClient.builder()
                .baseUrl(properties.inventory().baseUrl())
                .requestFactory(factory)
                .requestInterceptor((request, body, execution) -> {
                    // Forward the same correlation id so both services log
                    // under one greppable identifier for the same booking.
                    String cid = MDC.get(CorrelationIdFilter.MDC_KEY);
                    if (cid != null) {
                        request.getHeaders().add(CorrelationIdFilter.HEADER, cid);
                    }
                    return execution.execute(request, body);
                })
                .build();
    }
}
