package com.ticketing.booking.outbox;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

// The outbox row itself. Pure entity behaviour — a fresh row is unpublished
// and carries a generated event id (the dedup handle consumers rely on);
// markPublished() is the only thing that stamps published_at. No Spring/DB.
class OutboxEventTest {

    @Test
    void newEvent_generatesEventId_andStartsUnpublished() {
        OutboxEvent e = new OutboxEvent("42", "BookingConfirmed", "{\"bookingId\":42}", "corr-1");

        assertThat(e.getEventId()).isNotBlank();
        assertThat(e.getAggregateId()).isEqualTo("42");
        assertThat(e.getEventType()).isEqualTo("BookingConfirmed");
        assertThat(e.getCorrelationId()).isEqualTo("corr-1");
        assertThat(e.getPublishedAt()).isNull();
    }

    @Test
    void markPublished_stampsPublishedAt() {
        OutboxEvent e = new OutboxEvent("42", "BookingConfirmed", "{}", null);

        e.markPublished();

        assertThat(e.getPublishedAt()).isNotNull();
    }

    @Test
    void eachEvent_getsADistinctEventId() {
        OutboxEvent a = new OutboxEvent("1", "T", "{}", null);
        OutboxEvent b = new OutboxEvent("1", "T", "{}", null);

        // Same aggregate + type, but the event id is per-occurrence — that's
        // what lets a duplicated *delivery* be deduped while two genuine
        // events about the same booking stay distinct.
        assertThat(a.getEventId()).isNotEqualTo(b.getEventId());
    }
}
