#!/bin/bash
# Runs once, at first postgres container start, before the app starts.
# The main POSTGRES_DB (inventory) is already created by the postgres image
# from its env vars; we just add a SECOND database on the same server for
# booking-service — that's still "database-per-service" in the sense that
# matters (no cross-schema JOINs between services), while sharing one
# container is a deliberate local-dev compromise for this machine's
# Docker resource ceiling (see the memory note about the fragile daemon).
# In real AWS this becomes two separate RDS instances.
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE USER booking_user WITH PASSWORD 'booking_pass';
    CREATE DATABASE booking OWNER booking_user;
    GRANT ALL PRIVILEGES ON DATABASE booking TO booking_user;
EOSQL
