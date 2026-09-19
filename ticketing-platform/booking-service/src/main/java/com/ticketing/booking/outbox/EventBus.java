package com.ticketing.booking.outbox;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

// Week 3 stub — logs each event to stdout. Notification-service and
// analytics-service don't exist yet, and neither does a real broker
// (SNS/SQS). Once Phase 3 introduces real messaging, this bean gets
// swapped for one that publishes to SNS. The Outbox side doesn't
// change — only this component's implementation.
//
// The interface is deliberately narrow: publish(eventType, payload).
// Everything else (routing, retries at the broker level, DLQ) belongs to
// the real broker, not to this stub.
@Component
public class EventBus {

    private static final Logger log = LoggerFactory.getLogger(EventBus.class);

    public void publish(String eventType, String payload) {
        // Real impl (Phase 3) would call snsClient.publish(topic, payload).
        // Failures there → thrown, poller catches, row stays unpublished
        // for the next iteration. Same failure contract.
        log.info("event_published type={} payload={}", eventType, payload);
    }
}
