# payment-service

Third microservice on the ticketing track. Handles payment lifecycle
(authorize → capture → refund) with Adapter + Factory + Strategy for the
three stubbed payment methods (UPI, Card, NetBanking).

**Status:** Week 3 skeleton in flight. See `../WEEK3_DESIGN.md` for the
Day 1 design + interview questions. Junit tests deferred per user
directive.

---

## API surface

### `POST /payments` — authorize
Idempotent on `paymentSessionKey`.

```json
{
  "paymentSessionKey": "uuid-here",
  "bookingId": 42,
  "holderId": "user-A",
  "amount": 1200.00,
  "currency": "INR",
  "method": "UPI"
}
```

| Status | When |
|---|---|
| 201 Created | Fresh authorize, gateway approved → AUTHORIZED |
| 200 OK | Idempotent retry of an existing session key |
| 400 Bad Request | Validation error |
| 422 Unprocessable Entity | Same key + different body |
| 502 Bad Gateway | Gateway threw or declined |

### `POST /payments/{id}/capture`
Only valid from `AUTHORIZED`. Idempotent — capturing already-captured → 200 same body.

### `POST /payments/{id}/void`
Only valid from `AUTHORIZED`. Ends at `FAILED`. Idempotent.

### `POST /payments/{id}/refund`
Body: `{ "reason": "..." }`. Only valid from `CAPTURED`. Transitions
`CAPTURED → REFUND_PENDING → REFUNDED`. Idempotent.

### `GET /payments/{id}`
Returns the current state.

---

## State machine

```
INITIATED → AUTHORIZED → CAPTURED (happy terminal)
    │           │           │
    │           ↓           ↓
    └────────► FAILED    REFUND_PENDING → REFUNDED
                (terminal)      (terminal)
```

Enforced three ways: entity methods, DB check constraint (planned), `@Version` for races.

---

## Run locally

```bash
docker compose -f ../docker-compose.yml up -d postgres
./mvnw spring-boot:run
```

Runs on port `8083`.

Curl smoke:
```bash
curl -X POST http://localhost:8083/payments \
  -H "Content-Type: application/json" \
  -d '{"paymentSessionKey":"'$(uuidgen)'","bookingId":1,"holderId":"user-A","amount":500.00,"currency":"INR","method":"UPI"}'
```

## Configuration

| Property | Default | Purpose |
|---|---|---|
| `SERVER_PORT` | 8083 | HTTP port |
| `DB_HOST/PORT/NAME/USERNAME/PASSWORD` | localhost/5432/payment/payment_user/payment_pass | Own DB |
| `PAYMENT_AUTH_WINDOW_HOURS` | 1 | Auth expiry — auto-void after this |
| `PAYMENT_SIMULATE_AUTH_FAILURE` | false | Force authorize → decline (Day 5 experiment) |
| `PAYMENT_SIMULATE_CAPTURE_FAILURE` | false | Force capture → GatewayException |

---

## Package layout

- `controller/` — HTTP layer
- `service/PaymentService.java` — state machine driver, idempotency, gateway calls
- `service/AuthExpirySweepService.java` — `@Scheduled` void-sweep
- `adapter/` — `PaymentGateway` interface + 3 stubs + `PaymentGatewayFactory`
- `entity/` — `Payment`, `PaymentStatus`, `PaymentMethod`
- `repository/PaymentRepository.java` — Spring Data JPA
- `dto/` — request/response records
- `exception/` — `PaymentNotFoundException`, `InvalidPaymentTransitionException`, `GatewayException`, `IdempotencyKeyReuseException`, plus `GlobalExceptionHandler`
- `filter/CorrelationIdFilter.java` — MDC in/out; same shape as inventory + booking
- `config/PaymentProperties.java` — typed config

---

## Known trade-offs (deliberate)

1. **Gateway adapters are stubs.** Real Razorpay/Stripe integration is out of scope for Week 3.
2. **No JUnit tests yet.** User directive: implement + manual verify; junits at end-of-week clean pass.
3. **Auth window 1 hour in dev** — real gateways use 7 days; configurable via env for real deployment.
4. **`ddl-auto: update`** — Flyway migrations are the prod-safe answer, deferred.
5. **Sync REST calls to booking-service, no async.** Async events arrive Phase 3.
