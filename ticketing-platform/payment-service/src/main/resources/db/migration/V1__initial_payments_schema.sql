-- V1: payments table matching the Payment entity as of Week 3.
--
-- On fresh volumes this creates the schema from scratch. On volumes
-- that already have the table (from Week 3's ddl-auto: update runs),
-- Flyway's baseline-on-migrate=true records the current schema as the
-- baseline and skips this migration — same end state, no destructive
-- ops on existing data.

CREATE TABLE IF NOT EXISTS payments (
    id                    BIGSERIAL PRIMARY KEY,
    payment_session_key   VARCHAR(64)  NOT NULL,
    booking_id            BIGINT       NOT NULL,
    holder_id             VARCHAR(255) NOT NULL,
    amount                NUMERIC(12,2) NOT NULL,
    currency              VARCHAR(3)   NOT NULL,
    method                VARCHAR(32)  NOT NULL,
    status                VARCHAR(32)  NOT NULL DEFAULT 'INITIATED',
    gateway_ref           VARCHAR(128),
    created_at            TIMESTAMP WITH TIME ZONE NOT NULL,
    authorized_at         TIMESTAMP WITH TIME ZONE,
    captured_at           TIMESTAMP WITH TIME ZONE,
    refunded_at           TIMESTAMP WITH TIME ZONE,
    version               BIGINT,

    CONSTRAINT uk_payments_session_key UNIQUE (payment_session_key),
    CONSTRAINT payments_status_check CHECK (
        status IN ('INITIATED','AUTHORIZED','CAPTURED','FAILED','REFUND_PENDING','REFUNDED')
    ),
    CONSTRAINT payments_method_check CHECK (
        method IN ('UPI','CARD','NETBANKING')
    )
);
