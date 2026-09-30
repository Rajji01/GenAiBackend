package com.ticketing.booking.outbox;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ticketing.booking.filter.CorrelationIdFilter;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.slf4j.MDC;

import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.*;

// OutboxService.record — the write half of the outbox pattern. It serializes
// the payload and snapshots the current correlation id onto the row so the
// trace survives the later @Scheduled publish (Week 3 Day 6). Repo mocked,
// ObjectMapper real; no DB/Docker.
class OutboxServiceTest {

    private OutboxRepository repo;
    private OutboxService service;

    @BeforeEach
    void setUp() {
        repo = mock(OutboxRepository.class);
        service = new OutboxService(repo, new ObjectMapper());
        MDC.clear();
    }

    @AfterEach
    void tearDown() {
        MDC.clear();
    }

    @Test
    void record_serializesPayloadAndSnapshotsCorrelationIdFromMdc() {
        MDC.put(CorrelationIdFilter.MDC_KEY, "corr-42");

        service.record("42", "BookingConfirmed", Map.of("bookingId", 42));

        ArgumentCaptor<OutboxEvent> captor = ArgumentCaptor.forClass(OutboxEvent.class);
        verify(repo).save(captor.capture());
        OutboxEvent saved = captor.getValue();
        assertThat(saved.getAggregateId()).isEqualTo("42");
        assertThat(saved.getEventType()).isEqualTo("BookingConfirmed");
        assertThat(saved.getPayload()).contains("\"bookingId\":42");
        assertThat(saved.getCorrelationId()).isEqualTo("corr-42");
    }

    @Test
    void record_withNoCorrelationIdInMdc_savesNullCorrelationId() {
        service.record("7", "BookingConfirmed", Map.of("bookingId", 7));

        ArgumentCaptor<OutboxEvent> captor = ArgumentCaptor.forClass(OutboxEvent.class);
        verify(repo).save(captor.capture());
        assertThat(captor.getValue().getCorrelationId()).isNull();
    }

    @Test
    void record_unserializablePayload_throwsIllegalArgumentAndSavesNothing() {
        // A raw Object has no properties — Jackson refuses to serialize an
        // empty bean by default, which is exactly the "bad payload" case.
        assertThatThrownBy(() -> service.record("1", "T", new Object()))
                .isInstanceOf(IllegalArgumentException.class);
        verify(repo, never()).save(any());
    }
}
