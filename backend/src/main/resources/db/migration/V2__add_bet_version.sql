-- Adds an optimistic-locking version column to `bet`. This is the entity
-- where concurrent updates (two users/requests changing the same bet at the
-- same time) are a real, expected scenario, so it gets a @Version column
-- just like the optimistic-locking sandbox's `product` table already has.
ALTER TABLE bet ADD COLUMN version BIGINT NOT NULL DEFAULT 0;
