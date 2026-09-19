package com.ticketing.notification.controller;

import com.ticketing.notification.dto.NotificationResponse;
import com.ticketing.notification.dto.ReceiveEventRequest;
import com.ticketing.notification.entity.Notification;
import com.ticketing.notification.filter.CorrelationIdFilter;
import com.ticketing.notification.repository.NotificationRepository;
import com.ticketing.notification.service.NotificationService;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/notifications")
@RequiredArgsConstructor
public class NotificationController {

    private final NotificationService service;
    private final NotificationRepository repo;

    // Webhook — booking-service's EventBus posts here for every drained
    // outbox row. 202 Accepted (async intent) — we've received, further
    // processing is our own async concern.
    @PostMapping("/receive")
    public ResponseEntity<NotificationResponse> receive(
            @Valid @RequestBody ReceiveEventRequest req,
            HttpServletRequest servletReq) {
        String correlationId = servletReq.getHeader(CorrelationIdFilter.HEADER);
        Notification saved = service.receive(req, correlationId);
        return ResponseEntity.status(HttpStatus.ACCEPTED).body(NotificationResponse.from(saved));
    }

    @GetMapping("/holder/{holderId}")
    public List<NotificationResponse> byHolder(@PathVariable String holderId) {
        return repo.findByHolderIdOrderByReceivedAtDesc(holderId).stream()
                .map(NotificationResponse::from).toList();
    }

    @GetMapping("/booking/{bookingId}")
    public List<NotificationResponse> byBooking(@PathVariable Long bookingId) {
        return repo.findByBookingIdOrderByReceivedAtDesc(bookingId).stream()
                .map(NotificationResponse::from).toList();
    }
}
