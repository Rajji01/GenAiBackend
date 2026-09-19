# booking-service

Saga orchestrator for the ticketing-platform. Turns a client's booking
intent into a durable, idempotent workflow across `inventory-service` and
`payment-service` (stub for now, real Week 3).

**Status:** Week 2 Days 1–4 done — design + skeleton + idempotency + saga
wiring + Resilience4j + docker-compose files. Live-verification of the
compose stack and JUnit test pass are the remaining Week-2 items.
Companion notes: [`../SAGA_LAB.html`](../SAGA_LAB.html) (concepts,
decisions, tech glossary) and [`../WEEK2_DESIGN.md`](../WEEK2_DESIGN.md)
(Day 1 design deliverable).

---

## API surface

### `POST /bookings`

Create (or return the existing, on retry) a booking for the given seats.

**Headers**
- `Idempotency-Key: <uuid>` — **required**. Same key + same body → same
  booking returned (200 instead of 201). Same key + different body → 422.
- `X-Correlation-Id: <uuid>` — optional. Generated if absent, echoed back,
  forwarded on the outgoing inventory call.

**Body**
```json
{ "showId": 1, "seatIds": [5, 6, 7], "holderId": "user-42" }
```
Constraints: `showId` positive; `seatIds` non-empty + ≤ 6;
`holderId` non-blank.

**Responses**
| Status | When |
|---|---|
| 201 Created | New booking, saga succeeded (CONFIRMED) |
| 200 OK | Idempotent retry of an existing booking |
| 400 Bad Request | Missing header or invalid body |
| 422 Unprocessable | Idempotency-Key reused with different body |
| 502 Bad Gateway | Saga could not complete (inventory / payment failed). The `bookingId` is included in the `ProblemDetail`; the booking row is persisted as `FAILED` |

### `GET /bookings/{id}`

Returns the current state of a booking. `404` if not found.

---

## Run locally

Both services + Postgres + Redis with one command:
```bash
cp ../.env.example ../.env
docker compose --project-directory .. -f ../docker-compose.yml up --build
```

Or for a faster inner loop while iterating on booking-service:
```bash
docker compose -f ../docker-compose.yml up -d postgres redis inventory-service
./mvnw spring-boot:run
```

Hitting the running stack:
```bash
curl -X POST http://localhost:8082/bookings \
  -H "Idempotency-Key: $(uuidgen)" \
  -H "Content-Type: application/json" \
  -d '{"showId":1,"seatIds":[1,2],"holderId":"user-A"}'
```

## Test

```bash
./mvnw test
```
Real Postgres via Testcontainers. Currently 26 tests green (idempotency,
persistence, saga end-to-end with mocked inventory + payment).

---

## Configuration

All via env or `application.yml`. Keys worth knowing:

| Property | Default | Purpose |
|---|---|---|
| `SERVER_PORT` | 8082 | HTTP port |
| `DB_HOST` / `DB_PORT` / `DB_NAME` / `DB_USERNAME` / `DB_PASSWORD` | localhost / 5432 / booking / booking_user / booking_pass | Own Postgres database |
| `INVENTORY_BASE_URL` | `http://localhost:8081` | Outgoing calls to inventory-service; in compose becomes `http://inventory-service:8081` |
| `INVENTORY_TIMEOUT` | `3s` | Per-attempt connect + read timeout on outgoing inventory calls |
| `booking.payment.simulate-failure` | `false` | Force PaymentStub to always fail — Day 5 rollback experiment knob |
| `resilience4j.retry.instances.inventory.*` | See `application.yml` | Retry: max-attempts, wait-duration, exponential-backoff-multiplier |
| `resilience4j.circuitbreaker.instances.inventory.*` | See `application.yml` | CB: sliding-window-size, failure-rate-threshold, wait-duration-in-open-state |

---

## Architecture at a glance

```
Client
  │ POST /bookings (Idempotency-Key)
  ▼
BookingController
  │
  ▼
BookingService.create()
  │ 1. Look up by Idempotency-Key → existing? return.
  │ 2. INSERT PENDING row in own tx (REQUIRES_NEW).
  │ 3. Race loser catches unique-index violation, re-reads winner.
  │
  ▼ (only on freshly created)
BookingSagaService.runSaga()
  │ For each seat: InventoryClient.hold() [@Retry + @CircuitBreaker]
  │   → record hold_token on booking_seats
  │ → mark SEATS_HELD (own tx)
  │ → PaymentStub.charge()
  │ → mark PAYMENT_INITIATED (own tx)
  │ For each seat: InventoryClient.confirm() [@Retry + @CircuitBreaker]
  │ → mark CONFIRMED (own tx)
  │
  │ On any failure:
  │ → InventoryClient.release() for every held seat
  │ → mark FAILED (own tx)
  │ → throw SagaFailedException → 502
  ▼
BookingResponse (with final status)
```

Every state transition runs in its own `TransactionTemplate(REQUIRES_NEW)`
so each saga step commits before the next runs — that's what a saga
actually is, sequentially committed local transactions with named
compensations.

---

## Package layout

- `controller/` — thin HTTP layer, only knows the request/response shape
- `service/BookingService.java` — idempotency + persistence (boundary concern)
- `service/BookingSagaService.java` — state machine driver (domain concern)
- `service/PaymentStub.java` — always-success unless `simulate-failure=true`
- `client/InventoryClient.java` — the ONE place that calls inventory-service; wraps timeouts + retry + CB
- `client/InventoryClientException.java` + `InventoryTransientException.java` — the retry policy is the class hierarchy
- `entity/Booking.java` + `BookingSeat.java` + `BookingStatus.java` — the aggregate; named state-transition methods only, no raw `setStatus()`
- `repository/` — Spring Data JPA
- `dto/` — records; wire shapes; validation annotations
- `exception/GlobalExceptionHandler.java` — RFC 7807 `ProblemDetail`; copied from inventory-service (deliberately, not extracted)
- `filter/CorrelationIdFilter.java` — MDC in/out; copied from inventory-service
- `config/BookingProperties.java` + `InventoryRestClientConfig.java` — typed config + RestClient DI

---

## Known trade-offs (not bugs, deliberate)

1. **`ddl-auto: update`** in `application.yml` — fine for bootstrap, will need Flyway/Liquibase once there's real data to protect.
2. **Payment as an in-service stub** — Week 3 splits into a real `payment-service` container with Strategy for UPI/Card.
3. **One Postgres server, two databases** — deliberate local-dev compromise. Real AWS = two RDS instances. See `db-init/create-booking-db.sh`.
4. **`ddl-auto` + `spring.jpa.open-in-view=true` default warning** — accept for Week 2, revisit with Flyway.
5. **Timeout via `SimpleClientHttpRequestFactory`** — good enough; real prod would use `HttpComponentsClientHttpRequestFactory` with a pooled connection manager (~Week 5).
