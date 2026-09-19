package com.ticketing.notification.dto;

import com.ticketing.notification.entity.Notification;

import java.time.Instant;

public record NotificationResponse(
        Long id,
        String eventType,
        Long bookingId,
        String holderId,
        String payload,
        String correlationId,
        Instant receivedAt
) {
    public static NotificationResponse from(Notification n) {
        return new NotificationResponse(
                n.getId(), n.getEventType(), n.getBookingId(), n.getHolderId(),
                n.getPayload(), n.getCorrelationId(), n.getReceivedAt());
    }
}
