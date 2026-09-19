package com.ticketing.booking.outbox;

import com.ticketing.booking.config.BookingProperties;
import com.ticketing.booking.filter.CorrelationIdFilter;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.slf4j.MDC;
import org.springframework.http.MediaType;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;

import java.util.Map;

// Week 3 Day 5 rewire: was a stub that just logged; now HTTP-pushes each
// event to notification-service's /notifications/receive webhook. This
// finally exercises the outbox pattern end-to-end with a real consumer.
//
// The HTTP push is INTENTIONALLY simple — no Resilience4j retry/CB
// wrapping here. Reason: the outbox poller is already the retry
// mechanism. If publish throws, the outbox row stays unpublished and
// the next poll retries. That's the whole shape of at-least-once
// outbox — the transport just needs to be honest about failure.
//
// Phase 3 will swap this bean for one that publishes to SNS. Every
// caller (OutboxPublisher) is unchanged.
@Component
public class EventBus {

    private static final Logger log = LoggerFactory.getLogger(EventBus.class);

    private final RestClient restClient;

    public EventBus(BookingProperties properties) {
        int timeoutMs = (int) properties.notification().timeout().toMillis();
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(timeoutMs);
        factory.setReadTimeout(timeoutMs);

        this.restClient = RestClient.builder()
                .baseUrl(properties.notification().baseUrl())
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

    public void publish(String eventType, String payload) {
        try {
            restClient.post()
                    .uri("/notifications/receive")
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(Map.of(
                            "eventType", eventType,
                            "payload", payload
                    ))
                    .retrieve()
                    .toBodilessEntity();
            log.info("event_published type={} to=notification-service", eventType);
        } catch (RuntimeException ex) {
            // Fail-out to the caller (OutboxPublisher). Outbox row stays
            // unpublished; next poll retries. That's the at-least-once
            // guarantee's whole enforcement mechanism.
            log.warn("event_publish_failed type={} reason={}", eventType, ex.getMessage());
            throw ex;
        }
    }
}
