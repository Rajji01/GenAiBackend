package com.ticketing.notification.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ticketing.notification.dto.ReceiveEventRequest;
import com.ticketing.notification.entity.Notification;
import com.ticketing.notification.repository.NotificationRepository;
import lombok.RequiredArgsConstructor;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

// Receive an event, parse well-known fields from its JSON payload,
// dedupe on event_id, store, log.
//
// Week 3 Day 7 — dedup fully enforced now. Consumer contract from
// at-least-once outbox says "be idempotent"; this service now IS
// idempotent by design:
//   - Fast path: findByEventId → if present, skip immediately
//   - Slow path: even if two concurrent receives race past the check,
//     the UNIQUE constraint on notifications.event_id catches the loser
//     and DataIntegrityViolationException is caught + logged as dedup
@Service
@RequiredArgsConstructor
public class NotificationService {

    private static final Logger log = LoggerFactory.getLogger(NotificationService.class);

    private final NotificationRepository repo;
    private final ObjectMapper objectMapper;

    @Transactional
    public Notification receive(ReceiveEventRequest req, String correlationId) {
        // Fast dedup — the common case, no exception cost.
        var existing = repo.findByEventId(req.eventId());
        if (existing.isPresent()) {
            log.info("event_dedup_skip eventId={} type={} priorId={}",
                    req.eventId(), req.eventType(), existing.get().getId());
            return existing.get();
        }

        Long bookingId = null;
        String holderId = null;
        try {
            JsonNode node = objectMapper.readTree(req.payload());
            if (node.has("bookingId")) bookingId = node.get("bookingId").asLong();
            if (node.has("holderId")) holderId = node.get("holderId").asText();
        } catch (Exception parse) {
            log.warn("event_parse_failed eventId={} type={} reason={}",
                    req.eventId(), req.eventType(), parse.getMessage());
        }

        try {
            Notification saved = repo.save(new Notification(
                    req.eventId(), req.eventType(), bookingId, holderId,
                    req.payload(), correlationId));
            log.info("notification_received id={} eventId={} type={} bookingId={} holderId={} correlationId={}",
                    saved.getId(), req.eventId(), req.eventType(), bookingId, holderId, correlationId);
            return saved;
        } catch (DataIntegrityViolationException race) {
            // Slow path — two concurrent receives raced past the fast
            // dedup check. Unique constraint caught the loser. Re-read
            // the winning row and return it as if it were the response
            // (same response either way from the client's view).
            log.info("event_dedup_race eventId={} type={}", req.eventId(), req.eventType());
            return repo.findByEventId(req.eventId()).orElseThrow(() -> race);
        }
    }
}
