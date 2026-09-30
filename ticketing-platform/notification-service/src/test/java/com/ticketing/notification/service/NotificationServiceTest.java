package com.ticketing.notification.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ticketing.notification.dto.ReceiveEventRequest;
import com.ticketing.notification.entity.Notification;
import com.ticketing.notification.repository.NotificationRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.dao.DataIntegrityViolationException;

import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.*;

// Idempotent-consumer contract from the outbox pattern (WEEK3 Day 7): the
// same event delivered twice must be processed once. Two defences, both
// tested here — the fast findByEventId skip and the slow unique-constraint
// race catch — plus the degrade rule that a malformed payload never fails
// the receive. Repo mocked, ObjectMapper real (it's a pure parser); no DB,
// no Docker (same rationale as payment-service, AGENTS.md §7).
class NotificationServiceTest {

    private NotificationRepository repo;
    private NotificationService service;

    @BeforeEach
    void setUp() {
        repo = mock(NotificationRepository.class);
        service = new NotificationService(repo, new ObjectMapper());
        when(repo.save(any(Notification.class))).thenAnswer(inv -> inv.getArgument(0));
    }

    private ReceiveEventRequest req(String eventId, String payload) {
        return new ReceiveEventRequest(eventId, "BookingConfirmed", payload);
    }

    @Test
    void receive_freshEvent_parsesBookingAndHolderFromPayloadAndSaves() {
        when(repo.findByEventId("e1")).thenReturn(Optional.empty());

        service.receive(req("e1", "{\"bookingId\":42,\"holderId\":\"user-9\"}"), "corr-1");

        ArgumentCaptor<Notification> captor = ArgumentCaptor.forClass(Notification.class);
        verify(repo).save(captor.capture());
        Notification stored = captor.getValue();
        assertThat(stored.getEventId()).isEqualTo("e1");
        assertThat(stored.getBookingId()).isEqualTo(42L);
        assertThat(stored.getHolderId()).isEqualTo("user-9");
        assertThat(stored.getCorrelationId()).isEqualTo("corr-1");
    }

    @Test
    void receive_duplicateEventId_fastPathSkipsSaveAndReturnsExisting() {
        Notification prior = new Notification("e2", "BookingConfirmed", 1L, "u",
                "{}", "corr-old");
        when(repo.findByEventId("e2")).thenReturn(Optional.of(prior));

        Notification result = service.receive(req("e2", "{\"bookingId\":1}"), "corr-new");

        assertThat(result).isSameAs(prior);
        verify(repo, never()).save(any());
    }

    @Test
    void receive_concurrentRaceLoser_slowPathCatchesConstraintAndReturnsWinner() {
        Notification winner = new Notification("e3", "BookingConfirmed", 7L, "u7",
                "{}", "corr-win");
        // Fast check sees nothing; the winning thread inserted between the
        // check and this save, so save trips the unique constraint; the
        // catch re-reads and returns the winner.
        when(repo.findByEventId("e3")).thenReturn(Optional.empty(), Optional.of(winner));
        when(repo.save(any(Notification.class)))
                .thenThrow(new DataIntegrityViolationException("uk_notifications_event_id"));

        Notification result = service.receive(req("e3", "{\"bookingId\":7}"), "corr");

        assertThat(result).isSameAs(winner);
    }

    @Test
    void receive_malformedPayloadJson_degradesToNullFieldsButStillSaves() {
        when(repo.findByEventId("e4")).thenReturn(Optional.empty());

        service.receive(req("e4", "this-is-not-json{"), "corr");

        ArgumentCaptor<Notification> captor = ArgumentCaptor.forClass(Notification.class);
        verify(repo).save(captor.capture());
        // Parse failure must not turn a received event into a dropped one.
        assertThat(captor.getValue().getBookingId()).isNull();
        assertThat(captor.getValue().getHolderId()).isNull();
    }

    @Test
    void receive_payloadWithoutKnownFields_savesWithNulls() {
        when(repo.findByEventId("e5")).thenReturn(Optional.empty());

        service.receive(req("e5", "{\"somethingElse\":123}"), "corr");

        ArgumentCaptor<Notification> captor = ArgumentCaptor.forClass(Notification.class);
        verify(repo).save(captor.capture());
        assertThat(captor.getValue().getBookingId()).isNull();
        assertThat(captor.getValue().getHolderId()).isNull();
    }
}
