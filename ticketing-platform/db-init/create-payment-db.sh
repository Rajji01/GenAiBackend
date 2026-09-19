#!/bin/bash
# Runs alongside create-booking-db.sh on FIRST postgres container start
# (fresh volume only, per Bug 4 in SAGA_LAB). Creates the third database
# for payment-service on the same server.
#
# Same "database-per-service" invariant as the other two: no cross-service
# JOINs; physical isolation is local-dev-cheap. Real AWS makes this three
# separate RDS instances via env vars, no code change.
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE USER payment_user WITH PASSWORD 'payment_pass';
    CREATE DATABASE payment OWNER payment_user;
    GRANT ALL PRIVILEGES ON DATABASE payment TO payment_user;
EOSQL
