package com.ticketing.notification.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ticketing.notification.dto.ReceiveEventRequest;
import com.ticketing.notification.entity.Notification;
import com.ticketing.notification.repository.NotificationRepository;
import lombok.RequiredArgsConstructor;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

// Receive an event, parse well-known fields from its JSON payload,
// store, log. Real notification-sender would fan out from here (email,
// SMS, push); this stub just proves the pipe works end-to-end.
@Service
@RequiredArgsConstructor
public class NotificationService {

    private static final Logger log = LoggerFactory.getLogger(NotificationService.class);

    private final NotificationRepository repo;
    private final ObjectMapper objectMapper;

    @Transactional
    public Notification receive(ReceiveEventRequest req, String correlationId) {
        Long bookingId = null;
        String holderId = null;
        try {
            JsonNode node = objectMapper.readTree(req.payload());
            if (node.has("bookingId")) bookingId = node.get("bookingId").asLong();
            if (node.has("holderId")) holderId = node.get("holderId").asText();
        } catch (Exception parse) {
            // Payload isn't the expected shape — store anyway (raw text)
            // and log. Consumer contract for a stub: accept everything,
            // let downstream analysis decide what's useful.
            log.warn("event_parse_failed type={} reason={}", req.eventType(), parse.getMessage());
        }
        Notification saved = repo.save(new Notification(
                req.eventType(), bookingId, holderId, req.payload(), correlationId));
        log.info("notification_received id={} type={} bookingId={} holderId={} correlationId={}",
                saved.getId(), req.eventType(), bookingId, holderId, correlationId);
        return saved;
    }
}
