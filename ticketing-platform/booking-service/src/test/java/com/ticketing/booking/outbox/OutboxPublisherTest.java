package com.ticketing.booking.outbox;

import com.ticketing.booking.filter.CorrelationIdFilter;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.slf4j.MDC;
import org.springframework.data.domain.Pageable;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.List;
import java.util.Optional;
import java.util.concurrent.atomic.AtomicReference;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.*;

// The publisher drains unpublished rows and hands each to EventBus. Two
// invariants matter and both are Docker-free unit tests here:
//   1. At-least-once: if publish throws, the row is NOT marked published,
//      so the next poll retries it (that's the whole guarantee).
//   2. Correlation id captured on the row is restored to MDC around the
//      publish (so downstream sees the trace) and cleared afterwards (so it
//      doesn't leak onto the next event on the reused scheduled thread).
class OutboxPublisherTest {

    private OutboxRepository repo;
    private EventBus eventBus;
    private OutboxPublisher publisher;

    @BeforeEach
    void setUp() {
        repo = mock(OutboxRepository.class);
        eventBus = mock(EventBus.class);
        publisher = new OutboxPublisher(repo, eventBus);
        MDC.clear();
    }

    @AfterEach
    void tearDown() {
        MDC.clear();
    }

    private OutboxEvent event(long id, String correlationId) {
        OutboxEvent e = new OutboxEvent("agg", "BookingConfirmed", "{\"bookingId\":1}", correlationId);
        ReflectionTestUtils.setField(e, "id", id);
        return e;
    }

    @Test
    void drain_emptyBatch_touchesNothing() {
        when(repo.findUnpublished(any(Pageable.class))).thenReturn(List.of());

        publisher.drain();

        verifyNoInteractions(eventBus);
    }

    @Test
    void drain_publishSucceeds_marksRowPublished() {
        OutboxEvent e = event(1L, "corr-1");
        when(repo.findUnpublished(any(Pageable.class))).thenReturn(List.of(e));
        when(repo.findById(1L)).thenReturn(Optional.of(e));

        publisher.drain();

        verify(eventBus).publish(e.getEventId(), "BookingConfirmed", e.getPayload());
        assertThat(e.getPublishedAt()).isNotNull();
    }

    @Test
    void drain_publishThrows_leavesRowUnpublishedForNextPoll() {
        OutboxEvent e = event(1L, "corr-1");
        when(repo.findUnpublished(any(Pageable.class))).thenReturn(List.of(e));
        doThrow(new RuntimeException("event bus down")).when(eventBus).publish(any(), any(), any());

        publisher.drain(); // must swallow, not propagate

        assertThat(e.getPublishedAt()).isNull();
        verify(repo, never()).findById(anyLong()); // markPublished never reached
    }

    @Test
    void drain_restoresCorrelationIdDuringPublish_thenClearsItAfter() {
        OutboxEvent e = event(1L, "corr-xyz");
        when(repo.findUnpublished(any(Pageable.class))).thenReturn(List.of(e));
        when(repo.findById(1L)).thenReturn(Optional.of(e));
        AtomicReference<String> mdcDuringPublish = new AtomicReference<>();
        doAnswer(inv -> {
            mdcDuringPublish.set(MDC.get(CorrelationIdFilter.MDC_KEY));
            return null;
        }).when(eventBus).publish(any(), any(), any());

        publisher.drain();

        assertThat(mdcDuringPublish.get()).isEqualTo("corr-xyz");
        assertThat(MDC.get(CorrelationIdFilter.MDC_KEY)).isNull(); // cleared in finally
    }
}
