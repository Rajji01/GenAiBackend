-- V1: notifications table matching the Notification entity as of
-- Week 3 Day 7 (event_id UNIQUE = consumer-side dedup enforcement of
-- the at-least-once outbox contract).

CREATE TABLE IF NOT EXISTS notifications (
    id               BIGSERIAL PRIMARY KEY,
    event_id         VARCHAR(36)  NOT NULL,
    event_type       VARCHAR(64)  NOT NULL,
    booking_id       BIGINT,
    holder_id        VARCHAR(128),
    payload          TEXT         NOT NULL,
    correlation_id   VARCHAR(64),
    received_at      TIMESTAMP WITH TIME ZONE NOT NULL,

    CONSTRAINT uk_notifications_event_id UNIQUE (event_id)
);

CREATE INDEX IF NOT EXISTS idx_notifications_holder
    ON notifications (holder_id);
CREATE INDEX IF NOT EXISTS idx_notifications_booking
    ON notifications (booking_id);
