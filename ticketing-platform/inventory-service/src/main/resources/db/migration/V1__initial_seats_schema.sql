-- V1: seats table matching the Seat entity as of Week 1 (with the
-- Week 1 close-out booked_by_holder_id column for /confirm idempotency).
--
-- Same baseline-on-migrate=true story as the other services — this
-- runs on a fresh volume, is skipped on volumes that already had the
-- table created by ddl-auto: update.

CREATE TABLE IF NOT EXISTS seats (
    id                    BIGSERIAL PRIMARY KEY,
    show_id               BIGINT       NOT NULL,
    seat_number           VARCHAR(255) NOT NULL,
    status                VARCHAR(255) NOT NULL DEFAULT 'AVAILABLE',
    booked_by_holder_id   VARCHAR(255),
    version               BIGINT,

    CONSTRAINT uk_seats_show_seatnum UNIQUE (show_id, seat_number),
    CONSTRAINT seats_status_check CHECK (
        status IN ('AVAILABLE','HELD','BOOKED')
    )
);
