package com.ticketing.notification.dto;

import jakarta.validation.constraints.NotBlank;

// Incoming webhook payload from booking-service's EventBus. Body carries
// event_id (Week 3 Day 7 addition, drives consumer dedup) + event_type +
// payload as JSON string; we parse booking_id + holder_id from the
// payload for query convenience.
//
// This shape is intentionally the same as OutboxEvent's fields in
// booking-service — the wire contract between the two services.
// Phase 3 replaces the HTTP hop with SNS/SQS; the JSON shape stays.
public record ReceiveEventRequest(
        @NotBlank String eventId,
        @NotBlank String eventType,
        @NotBlank String payload
) {}
