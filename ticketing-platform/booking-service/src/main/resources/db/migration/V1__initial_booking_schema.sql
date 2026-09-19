-- V1: bookings + booking_seats + outbox_events matching the Week 3
-- close-out entity shape (Booking, BookingSeat, OutboxEvent).
--
-- baseline-on-migrate=true means volumes that already went through
-- ddl-auto: update in Weeks 1-3 skip this and keep their existing
-- rows; fresh volumes create everything from here. Same terminal
-- schema either way.

CREATE TABLE IF NOT EXISTS bookings (
    id                BIGSERIAL PRIMARY KEY,
    idempotency_key   VARCHAR(64)  NOT NULL,
    request_hash      VARCHAR(64)  NOT NULL,
    show_id           BIGINT       NOT NULL,
    holder_id         VARCHAR(255) NOT NULL,
    status            VARCHAR(255) NOT NULL DEFAULT 'PENDING',
    payment_ref       VARCHAR(255),
    payment_id        BIGINT,
    refund_pending    BOOLEAN      NOT NULL DEFAULT FALSE,
    created_at        TIMESTAMP WITH TIME ZONE NOT NULL,
    confirmed_at      TIMESTAMP WITH TIME ZONE,
    version           BIGINT,

    CONSTRAINT uk_bookings_idempotency_key UNIQUE (idempotency_key),
    CONSTRAINT bookings_status_check CHECK (
        status IN (
            'PENDING','SEATS_HELD','PAYMENT_INITIATED',
            'CONFIRMED','FAILED','EXPIRED'
        )
    )
);

CREATE TABLE IF NOT EXISTS booking_seats (
    id           BIGSERIAL PRIMARY KEY,
    booking_id   BIGINT NOT NULL,
    seat_id      BIGINT NOT NULL,
    hold_token   VARCHAR(255),
    released_at  TIMESTAMP WITH TIME ZONE,

    CONSTRAINT uk_booking_seats_booking_seat UNIQUE (booking_id, seat_id)
);

-- Outbox pattern (Week 3 Day 3). One row per domain event, published
-- by OutboxPublisher (@Scheduled poller). event_id uniqueness enforces
-- the at-least-once contract — consumers dedupe on event_id.
CREATE TABLE IF NOT EXISTS outbox_events (
    id               BIGSERIAL PRIMARY KEY,
    event_id         VARCHAR(36)  NOT NULL,
    aggregate_id     VARCHAR(64)  NOT NULL,
    event_type       VARCHAR(64)  NOT NULL,
    payload          TEXT         NOT NULL,
    created_at       TIMESTAMP WITH TIME ZONE NOT NULL,
    published_at     TIMESTAMP WITH TIME ZONE,
    correlation_id   VARCHAR(64),

    CONSTRAINT uk_outbox_event_id UNIQUE (event_id)
);

-- Fast scan for the unpublished-events poll loop. Full index (not
-- partial WHERE published_at IS NULL) to match how JPA's @Index would
-- have created it under ddl-auto — stays validate-compatible.
CREATE INDEX IF NOT EXISTS idx_outbox_unpublished
    ON outbox_events (published_at);
