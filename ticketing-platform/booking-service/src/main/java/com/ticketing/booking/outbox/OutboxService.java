package com.ticketing.booking.outbox;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ticketing.booking.filter.CorrelationIdFilter;
import lombok.RequiredArgsConstructor;
import org.slf4j.MDC;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

// Convenience wrapper — call this from within a business transaction to
// write an event to the outbox atomically with your state change. The
// method inherits the caller's transaction (PROPAGATION_REQUIRED by
// default) — that's the whole point, both writes commit or roll back
// together.
//
// Week 3 Day 6: captures the current MDC correlation id at record time.
// The publisher runs in a @Scheduled thread with empty MDC, so without
// this the tracing context would die at the outbox boundary. Now the
// correlation id rides on the row itself and gets restored to MDC just
// before publish, so notification-service sees the same trace id
// booking-service used when writing the row.
@Service
@RequiredArgsConstructor
public class OutboxService {

    private final OutboxRepository repo;
    private final ObjectMapper objectMapper;

    // MANDATORY propagation: refuse to run outside a transaction. Callers
    // MUST be @Transactional or use a TransactionTemplate — a naked call
    // would defeat outbox's whole atomicity guarantee.
    @Transactional(propagation = Propagation.MANDATORY)
    public void record(String aggregateId, String eventType, Object payload) {
        String json;
        try {
            json = objectMapper.writeValueAsString(payload);
        } catch (JsonProcessingException e) {
            throw new IllegalArgumentException(
                    "Cannot serialize event payload of type " + payload.getClass(), e);
        }
        String correlationId = MDC.get(CorrelationIdFilter.MDC_KEY); // may be null in a @Scheduled write path
        repo.save(new OutboxEvent(aggregateId, eventType, json, correlationId));
    }
}
