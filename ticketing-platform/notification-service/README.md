# notification-service

Fourth microservice on the ticketing track. **Downstream consumer of
booking events** — the piece that finally exercises the outbox pattern
Week 3 introduced. Port 8084.

**Status:** Week 3 Day 5 addition. Local stub, no email/SMS integration
yet — receives + logs + stores.

**Why it exists now:** Week 3 built the outbox in booking-service but
its `EventBus` was a stub that just logged. This service is the first
real consumer — proves the whole producer → transport → consumer pipe
end-to-end. Phase 3 will swap the HTTP transport for SNS/SQS; the
consumer's own shape stays the same.

---

## API surface

### `POST /notifications/receive` — webhook

Called by booking-service's `EventBus.publish(...)` implementation for
every drained outbox row.

```json
{
  "eventType": "BookingConfirmed",
  "payload": "{\"bookingId\":33,\"holderId\":\"user-A\",...}"
}
```

**Headers:** `X-Correlation-Id` (forwarded by booking-service — same
trace id spans all four services now).

**Responses:** `202 Accepted` on success. Body echoes the stored
notification.

### `GET /notifications/holder/{holderId}`
### `GET /notifications/booking/{bookingId}`

Return stored notifications for a holder or booking. Sorted by
`received_at` desc.

---

## What's stored

One row per event received. Full JSON payload preserved, plus
denormalized `booking_id` / `holder_id` for query convenience, plus the
producer's `correlation_id`.

**No deduplication.** The outbox contract is at-least-once, and this
stub deliberately doesn't dedupe — so if you see two rows for the same
(booking_id, event_type), you know the poller delivered twice. Real
prod would dedupe by event id (which would need to be added to the
outbox payload).

---

## Run locally

```bash
docker compose -f ../docker-compose.yml up -d postgres
./mvnw spring-boot:run
```

---

## Package layout

- `controller/NotificationController` — three endpoints
- `service/NotificationService` — parse payload, save, log
- `entity/Notification` — the persisted row
- `repository/NotificationRepository` — Spring Data JPA
- `dto/ReceiveEventRequest`, `NotificationResponse` — records
- `exception/GlobalExceptionHandler` — RFC 7807 (fourth copy across the platform, per the deliberate no-shared-lib rule)
- `filter/CorrelationIdFilter` — MDC in/out (fourth copy)

---

## Known deferrals

1. **Deduplication by event id** — outbox payload would need to carry a stable event id; consumer would upsert-by-that-id. Not done Week 3.
2. **Retry on receive failure** — booking-service's EventBus does its own retry via Resilience4j; if this service is down, the outbox row stays unpublished and gets retried next poll. Same guarantee mechanism.
3. **Real notification transport** — email/SMS/push. Every "real" notification-sender is a fan-out from here; this stub just proves the receive path.
4. **JUnit tests** — deferred per user directive; end-of-week clean pass.
