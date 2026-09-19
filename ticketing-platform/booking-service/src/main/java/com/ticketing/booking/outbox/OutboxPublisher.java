package com.ticketing.booking.outbox;

import com.ticketing.booking.filter.CorrelationIdFilter;
import lombok.RequiredArgsConstructor;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.slf4j.MDC;
import org.springframework.data.domain.PageRequest;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;

// The same-process outbox poller. Drains unpublished rows every N ms
// (booking.outbox.poll-interval-ms), publishes each to EventBus, marks
// the row published on success. If publish throws, the row stays
// unpublished → picked up next iteration → **at-least-once delivery**,
// which means consumers must be idempotent.
//
// Batched (max 100 per poll) so a big backlog is drained gradually
// without holding one massive transaction. Publish is intentionally
// OUTSIDE the DB transaction — if EventBus is slow, we don't hold locks.
@Component
@RequiredArgsConstructor
public class OutboxPublisher {

    private static final Logger log = LoggerFactory.getLogger(OutboxPublisher.class);
    private static final int BATCH_SIZE = 100;

    private final OutboxRepository repo;
    private final EventBus eventBus;

    @Scheduled(fixedDelayString = "${booking.outbox.poll-interval-ms:2000}")
    public void drain() {
        List<OutboxEvent> batch = findBatch();
        if (batch.isEmpty()) return;
        for (OutboxEvent event : batch) {
            // Week 3 Day 6 fix — restore the correlation id captured at
            // record time so downstream services and logs see the same
            // trace across the @Scheduled boundary. Cleared in finally
            // to avoid leaking one event's id onto the next event's
            // publish (the scheduled thread is reused across events).
            String captured = event.getCorrelationId();
            if (captured != null) {
                MDC.put(CorrelationIdFilter.MDC_KEY, captured);
            }
            try {
                eventBus.publish(event.getEventId(), event.getEventType(), event.getPayload());
                markPublished(event.getId());
            } catch (RuntimeException ex) {
                log.warn("outbox_publish_failed eventId={} type={} reason={}",
                        event.getId(), event.getEventType(), ex.getMessage());
                // Leave unpublished; next iteration retries. If the same
                // event keeps failing, a real broker's DLQ is the answer
                // — Phase 3.
            } finally {
                MDC.remove(CorrelationIdFilter.MDC_KEY);
            }
        }
    }

    @Transactional(readOnly = true)
    protected List<OutboxEvent> findBatch() {
        return repo.findUnpublished(PageRequest.of(0, BATCH_SIZE));
    }

    @Transactional
    protected void markPublished(Long id) {
        repo.findById(id).ifPresent(event -> {
            event.markPublished();
            repo.save(event);
        });
    }
}
