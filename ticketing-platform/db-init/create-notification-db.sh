#!/bin/bash
# Runs on FIRST postgres container start against a fresh volume, alongside
# create-booking-db.sh and create-payment-db.sh. Creates the fourth
# database on the shared server for notification-service.
#
# Same "database-per-service" invariant: no cross-service JOINs; physical
# isolation is a local-dev compromise (four RDS instances in real AWS).
#
# NOTE: this script runs ONLY on a fresh volume. If pgdata already has
# other databases, this file silently isn't executed — Bug 4 pattern.
# Manual create if needed:
#   docker exec ticketing-platform-postgres-1 psql -U inventory_user -d postgres \
#     -c "CREATE USER notification_user WITH PASSWORD 'notification_pass';"
#   docker exec ticketing-platform-postgres-1 psql -U inventory_user -d postgres \
#     -c "CREATE DATABASE notification OWNER notification_user;"
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE USER notification_user WITH PASSWORD 'notification_pass';
    CREATE DATABASE notification OWNER notification_user;
    GRANT ALL PRIVILEGES ON DATABASE notification TO notification_user;
EOSQL
