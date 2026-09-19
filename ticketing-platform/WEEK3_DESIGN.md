# Week 3, Day 1 — payment-service + outbox + saga rollback DESIGN (no code)

> Deliverable per `ROADMAP.md` §4 Week 3: **payment-service stub + outbox
> pattern + saga rollback + dangling recovery**. Following the Week 2 Day 1
> pattern — pure design first, code from Day 2. **Zero code today.**

The 4 concerns split as:

1. **payment-service** — extract payment from booking-service (currently a
   `PaymentStub` class inside booking-service) into a real separate service
   with Adapter + Factory + Strategy for payment methods.
2. **Outbox pattern** — booking's own domain events (`BookingConfirmed`,
   `BookingFailed`) published reliably even if the process crashes between
   DB commit and event dispatch. Foundation for Phase 3's real
   SNS/SQS messaging.
3. **Saga rollback** — refine what "compensate" means now that payment is a
   real cross-service call: partial confirm-fail with refund, timeout
   ambiguity, in-doubt state.
4. **Dangling recovery** — booking crash mid-saga leaves a row in
   `PENDING` / `SEATS_HELD` / `PAYMENT_INITIATED` — nobody drives it
   forward. A recovery sweep picks it up.

---

## 1. payment-service — service boundary + state model

### Why a separate service now (not Week 2)

Payment lifecycle is genuinely different from booking:

- **Different actors** — payment gateway (external), refund team (ops)
- **Different failure modes** — network to gateway, chargebacks, PCI-scoped data
- **Different scaling profile** — refunds spike weeks after bookings peak
- **Different data ownership** — booking-service should NEVER touch payment
  rows directly (analogous to how booking never touches `seats`)

Week 2's `PaymentStub` inside booking-service was a deliberate placeholder.
Week 3 is when it earns its own container.

### `Payment` state machine

| State | Meaning | Terminal? |
|---|---|---|
| `INITIATED` | Payment row inserted, gateway call not yet made | no |
| `AUTHORIZED` | Gateway returned success; funds reserved but not captured | no |
| `CAPTURED` | Funds actually moved from customer → merchant | **yes** (happy) |
| `FAILED` | Gateway declined / user cancelled | **yes** |
| `REFUND_PENDING` | Capture succeeded but downstream (confirm) failed — flagged for refund | no |
| `REFUNDED` | Refund actually processed | **yes** |

### Transition table

| From | Trigger | To |
|---|---|---|
| — | booking-service POST `/payments` | `INITIATED` |
| `INITIATED` | Gateway auth call succeeds | `AUTHORIZED` |
| `INITIATED` | Gateway declines / times out | `FAILED` |
| `AUTHORIZED` | booking-service POST `/payments/{id}/capture` | `CAPTURED` |
| `AUTHORIZED` | Auth expires (typical 7-day window in real gateways, 1-hour stub) | `FAILED` |
| `CAPTURED` | ops POST `/payments/{id}/refund` (from booking failure signal) | `REFUND_PENDING` → `REFUNDED` |

Same three-layer enforcement as `Booking`:
1. Entity methods (`markAuthorized`, `markCaptured`, `markFailed`, `markRefunded`) validate current state
2. DB check constraint on `payments.status` (trigger blocks terminal-row updates)
3. `@Version` for concurrent transitions

### Two-step vs one-step charge — why two steps

Real gateways separate **authorize** (reserve money, reversible) from
**capture** (actually take money, harder to reverse). Modeling this in the
stub too, because it's the difference that makes the compensating path
clean:

- **Auth fail** → seat release, no money moved, cheap rollback
- **Auth succeed → confirm fail** → simple void of auth (no refund needed
  yet, funds never left customer)
- **Auth succeed → capture succeed → confirm fail** → **actual refund
  needed** (this is the hard case Week 2 had flagged as `refund_pending`)

Week 2 collapsed auth+capture into `charge()`. Week 3 splits them, which
makes booking-service's saga cleaner too.

### API contract

**`POST /payments`** — Initiate a payment
- Body: `{ bookingId, amount, currency, method: "UPI" | "CARD" | "NETBANKING", holderId, paymentSessionKey }`
- Idempotent on `paymentSessionKey` (client-supplied, like booking's `Idempotency-Key`)
- Returns 201 with `PaymentResponse { paymentId, status: "AUTHORIZED", ... }`

**`POST /payments/{id}/capture`** — Capture an authorized payment
- Body: `{}`
- Idempotent — same call twice returns `CAPTURED` state either way
- Returns 200 with `PaymentResponse { status: "CAPTURED", ... }`

**`POST /payments/{id}/void`** — Void an unauthorized payment (auth reversal)
- Idempotent
- Only valid from `AUTHORIZED` (not `CAPTURED`)
- Returns 200 with `{ status: "FAILED", ... }`

**`POST /payments/{id}/refund`** — Refund a captured payment
- Body: `{ reason }`
- Idempotent
- Only valid from `CAPTURED`
- Returns 200 with `{ status: "REFUND_PENDING", ... }` (async — refunds take real time)

**`GET /payments/{id}`** — Read

---

## 2. Adapter + Factory + Strategy — the LLD triad

Three patterns, deliberately chosen for the payment domain:

### Adapter — one interface, many gateway shapes

```
interface PaymentGateway {
    AuthResult authorize(AuthRequest req);
    CaptureResult capture(String gatewayRef);
    VoidResult voidAuth(String gatewayRef);
    RefundResult refund(String gatewayRef, Money amount);
}

UPIAdapter implements PaymentGateway { /* stubs UPI-shaped calls */ }
CardAdapter implements PaymentGateway { /* stubs Card-shaped calls */ }
NetBankingAdapter implements PaymentGateway { /* stubs NB-shaped calls */ }
```

Every real gateway (Razorpay, Stripe, PhonePe) has a different wire
protocol. Adapter isolates the payment-service's own logic from that
noise. Adding a new gateway = write one new adapter, nothing else changes.

### Factory — pick an adapter from the request

```
PaymentGateway forMethod(PaymentMethod method) {
    return switch (method) {
        case UPI -> upiAdapter;
        case CARD -> cardAdapter;
        case NETBANKING -> nbAdapter;
    };
}
```

Not a `new UPIAdapter()` at every call site — a `PaymentGatewayFactory`
bean that resolves at request-handling time. This is where DI does real
work: each adapter has its own configuration (base URL, timeout, secret).

### Strategy — where it actually earns its cost

Payment method choice is the caller's Strategy — booking-service passes
`method: "UPI"` in the request. But there are **internal** strategies too
where it earns its cost:

- **Retry strategy** — UPI retries differently from card (idempotency
  semantics differ)
- **Timeout strategy** — Card auth is slower than UPI
- **Fallback strategy** — UPI times out → try Card? Depends on business
  rules

For Day 1's design, Strategy stays as the *decision* — Day 2 code will
have exactly one strategy per adapter. Second-strategy comes when a real
different behavior earns its own class.

---

## 3. Outbox pattern — the reliable event publisher

### The problem outbox solves

booking-service commits a `Booking` row as `CONFIRMED`. Now it wants to
tell downstream services (notification, analytics, future ai-service):
"a booking was confirmed."

Naive approach:
```java
@Transactional
public void confirm(...) {
    booking.markConfirmed();
    bookingRepository.save(booking);
    eventPublisher.publish(new BookingConfirmed(...));  // ← the trap
}
```

**Trap:** `eventPublisher.publish(...)` might succeed while the surrounding
transaction rolls back → event fired for a booking that doesn't exist.
Or the reverse: commit succeeds, publisher call fails (network) → booking
CONFIRMED but nobody hears about it.

This is the **dual-write problem** — can't atomically commit to DB and
publish to a message broker.

### Outbox — the pattern

Write the event as a row in a table (`outbox`) inside the SAME transaction
as the booking state change:

```sql
BEGIN;
  UPDATE bookings SET status = 'CONFIRMED' WHERE id = 5;
  INSERT INTO outbox (aggregate_id, event_type, payload, created_at)
    VALUES (5, 'BookingConfirmed', '{...json...}', NOW());
COMMIT;
```

Both writes atomic. Now a **separate publisher process** polls the
`outbox` table, publishes each unpublished row to the message broker, then
marks it published:

```
loop every 2 seconds:
    rows = SELECT * FROM outbox WHERE published_at IS NULL ORDER BY id LIMIT 100
    for each row:
        broker.publish(row.event_type, row.payload)
        UPDATE outbox SET published_at = NOW() WHERE id = row.id
```

### Why this actually works

- If the DB commit fails → outbox row not inserted → nothing to publish → correct
- If the broker publish fails → outbox row not marked → picked up next poll → correct
- If the publisher crashes mid-publish → some events may publish twice → consumers must be idempotent (this is the trade-off, and the consumer contract)

**Guarantee:** at-least-once delivery. **Not** exactly-once (that's
philosophically impossible in a distributed system without consumer
cooperation).

### Table schema (booking-service side)

```sql
CREATE TABLE outbox (
    id           BIGSERIAL PRIMARY KEY,
    aggregate_id VARCHAR(64) NOT NULL,   -- the booking id
    event_type   VARCHAR(64) NOT NULL,   -- 'BookingConfirmed' etc
    payload      JSONB NOT NULL,          -- event body
    created_at   TIMESTAMPTZ NOT NULL,
    published_at TIMESTAMPTZ,             -- NULL until published

    INDEX idx_outbox_unpublished (published_at) WHERE published_at IS NULL
);
```

Partial index on unpublished rows keeps the poll fast even when the table
is huge and mostly-published.

### Publisher — options

- **Same-process poller** — a `@Scheduled` in booking-service that polls its
  own outbox and publishes. Simplest, fine for Week 3.
- **Debezium/CDC** — Postgres logical replication streams the outbox table
  to Kafka. Zero-latency, prod-grade. Overkill for Week 3, right choice
  for Phase 3's real messaging.
- **Sidecar** — a separate process/pod reading the outbox. Middle ground.

**Week 3 chooses the same-process poller.** Real broker (SNS/SQS) arrives
Phase 3; the poller then either publishes to SNS or the CDC pattern
replaces it.

### The broker in Week 3 — deliberately a "log broker"

For Week 3 the "broker" is just an in-process `EventBus` that logs the
event to stdout. Notification-service and analytics-service don't exist
yet. The important thing is that **outbox rows drain correctly**, not
that the events land anywhere in particular. Phase 3 swaps EventBus for
SNS with zero change to the outbox side.

---

## 4. Saga rollback — the harder rollback shapes now that payment is a service

Week 2's saga rollback was simple: any downstream failure → release seats
+ mark FAILED. Week 3's payment split introduces new failure shapes.

### The failure matrix

| Step | Failure | Compensation | Refund needed? |
|---|---|---|---|
| Hold seats | Any seat 409 | Release the ones we did hold | no |
| Payment authorize | Gateway declines | Release seats | no |
| Payment authorize | Timeout / network error | Release seats + **query payment-service** to know outcome | maybe (see below) |
| Payment capture | Fails after authorize | **Void** the authorization + release seats | no (auth voided) |
| Inventory confirm | Fails after capture | **Refund** capture + release seats + mark booking `FAILED_REFUND_PENDING` | **yes** |

### The in-doubt payment case

The nastiest: booking-service calls `POST /payments` and the network drops
before response arrives. Did the payment actually authorize? Unknown.

**Wrong answer:** release seats + mark FAILED. Because if the auth
actually succeeded, we've now abandoned an authorized transaction that
will time out silently, and the customer sees a hold on their card without
a booking to show for it.

**Right answer:** query payment-service. The `paymentSessionKey`
booking-service sent was designed exactly for this — idempotency-key
semantics. `GET /payments?sessionKey=xxx` returns the actual state.

- If `AUTHORIZED` → we now know, continue capture
- If `FAILED` → clean rollback
- If `INITIATED` (payment-service saw it but gateway didn't respond yet) → recovery sweep will pick it up

**booking-service should never assume the outcome of a step it lost the
response to.** Always query. This is the discipline distributed saga
requires.

### The refund case (booking failed after capture)

Money moved (`CAPTURED`), but inventory `/confirm` then failed. Options:

1. **Auto-refund immediately** — call `POST /payments/{id}/refund`, mark
   booking `FAILED`. Simple. Assumes refund always succeeds.
2. **Flag for ops review** — mark booking `FAILED_REFUND_PENDING`, refund
   handled offline. Safer, requires ops process.

Week 3 chooses **auto-refund but keep the flag**. The `POST
/payments/{id}/refund` call goes into the same
Resilience4j-wrapped pattern as inventory calls: retry transient, CB, etc.
If retries exhaust, booking gets `FAILED_REFUND_PENDING` and ops queue
picks it up.

---

## 5. Dangling recovery — the crash mid-saga

### The scenarios

booking-service crashes:
- After INSERT `PENDING` but before hold call → row in `PENDING`, seats untouched
- After hold succeeds but before payment call → row in `SEATS_HELD`, seats held, no payment
- After payment authorize but before capture → row in `PAYMENT_INITIATED`, auth ticking
- After capture but before `/confirm` → row in `PAYMENT_INITIATED`, money moved, seats not confirmed
- After partial confirm (2 of 5 seats) → row in `PAYMENT_INITIATED`, 2 seats BOOKED + 3 HELD

Nobody is driving any of these forward. Timer starts ticking (5-min hold
TTL, 1-hour payment auth window). Without recovery, seats leak or funds
stay authorized indefinitely.

### The sweep

`BookingRecoveryService` — `@Scheduled` every 60 seconds:

```
for each booking WHERE status IN ('PENDING', 'SEATS_HELD', 'PAYMENT_INITIATED')
                 AND created_at < NOW() - 2 minutes  -- age filter avoids racing an in-flight saga
loop:
    switch (booking.status):
        case PENDING:
            → mark FAILED (never got past insert, safe to fail)
        case SEATS_HELD:
            → check payment-service by sessionKey
                if no payment record → try /release each seat, mark FAILED
                if AUTHORIZED → resume from that point (call capture)
                if FAILED → release seats, mark FAILED
        case PAYMENT_INITIATED:
            → check payment-service by paymentId
                if AUTHORIZED not yet CAPTURED → capture + confirm
                if CAPTURED, need to check inventory
                    if not confirmed → try /confirm again
                    if partial confirm → refund + mark FAILED_REFUND_PENDING
```

**Age filter is critical.** A booking created 10 seconds ago is probably
still executing in another request's saga. The sweep must never race an
in-flight saga.

### Idempotency saves the sweep

Every operation the sweep might invoke is idempotent by design:
- inventory `/release` — no-op if seat already released
- inventory `/confirm` — same response for retry
- payment `/capture` — same result for retry
- payment `/refund` — same result for retry

So the sweep can safely re-drive a booking from any state without worrying
about double-charging or double-releasing.

### Alternative — event-sourced saga

A more mature architecture stores each saga step as an event
(`SagaStarted`, `SeatsHeld`, `PaymentAuthorized`, ...) and the saga
executor is stateless — it re-plays events to determine current step.
Debezium + Kafka enable this. **Overkill for Week 3.** ROADMAP has it
implicitly in Phase 3 event-driven maturity.

---

## 6. Directory-per-service layout — what's changing

Current:
```
ticketing-platform/
├── inventory-service/
├── booking-service/
└── docker-compose.yml
```

After Week 3:
```
ticketing-platform/
├── inventory-service/          (unchanged from Week 1)
├── booking-service/            (outbox added, PaymentStub removed, PaymentClient added)
├── payment-service/            (NEW — Java 17 Spring Boot, own Postgres DB)
├── db-init/
│   ├── create-booking-db.sh    (existing)
│   └── create-payment-db.sh    (NEW)
└── docker-compose.yml          (updated — payment-service added)
```

Three services on one Postgres server, three databases:
`inventory`, `booking`, `payment`. Same "database-per-service" invariant.

---

## 7. Sequence diagrams

### Happy path — with payment split

```
Client        booking          inventory        payment          gateway
  │  POST /bookings  │              │              │              │
  │─────────────────►│              │              │              │
  │                  │  INSERT PENDING             │              │
  │                  │  /hold (×N) ►│              │              │
  │                  │◄─────────────│              │              │
  │                  │  SEATS_HELD                 │              │
  │                  │                             │              │
  │                  │  POST /payments (sessionKey) ►             │
  │                  │                     INSERT INITIATED       │
  │                  │                    │  authorize ►          │
  │                  │                    │◄─────────  auth OK    │
  │                  │                    │  mark AUTHORIZED      │
  │                  │◄──────  201 { AUTHORIZED }                 │
  │                  │  PAYMENT_INITIATED                         │
  │                  │                                            │
  │                  │  POST /payments/{id}/capture               │
  │                  │  ─────────────────►                        │
  │                  │                    capture ►               │
  │                  │                    │◄──────  capture OK    │
  │                  │                    │  mark CAPTURED        │
  │                  │◄─────  200 { CAPTURED }                    │
  │                  │                                            │
  │                  │  /confirm (×N) ►                           │
  │                  │◄─────────────                              │
  │                  │  CONFIRMED
  │                  │  outbox INSERT BookingConfirmed
  │◄──────  201 { CONFIRMED }
                            │
                    [outbox poller, seconds later]
                            │
                            outbox → EventBus.publish(BookingConfirmed)
```

### Refund path — capture succeeded, confirm failed

```
[... booking to PAYMENT_INITIATED + CAPTURED as above ...]

booking → /confirm seat[3]  → inventory  → 409
booking → refund needed:
          /release each held seat
          /payments/{id}/refund → payment → gateway refund → REFUND_PENDING
          mark booking FAILED_REFUND_PENDING
          outbox INSERT BookingFailedWithRefund
                            │
                    [outbox poller]
                            │
                            EventBus.publish(BookingFailedWithRefund)
                                → ops queue notified
```

### Recovery — booking crashed after CAPTURED but before /confirm

```
[Time passes. BookingRecoveryService @Scheduled fires 60s later.]

Sweep query: bookings WHERE status='PAYMENT_INITIATED' AND created_at < now()-2m
Found: booking id=7

Sweep asks payment-service: GET /payments?bookingId=7
  → { status: 'CAPTURED', paymentRef: 'pay-42' }

Sweep now drives forward:
  → inventory /confirm each seat (idempotent — safe if already done)
  → mark booking CONFIRMED
  → outbox INSERT BookingConfirmed
Done. As if the crash never happened.
```

---

## 8. Open questions — decide before Day 2

Same pattern as Week 2's Day 1:

1. **Payment auth window** — real gateways use 7 days; stub too long for
   dev. **Decision: 1 hour default in dev**, configurable via
   `payment.auth-window-hours`. Sweep queries payments approaching this
   window to void proactively.

2. **Outbox row retention** — after `published_at IS NOT NULL`, keep for
   how long? **Decision: 30 days**, then a nightly job deletes older
   rows. Real prod could use table partitioning; overkill for Week 3.

3. **PaymentClient in booking-service** — same style as `InventoryClient`
   (RestClient + Resilience4j). Explicitly *NOT* extracted to a shared
   lib. Duplication over deploy-cycle coupling, same rule as
   GlobalExceptionHandler + CorrelationIdFilter.

4. **Payment DB — same Postgres server or separate?** For Week 3 local
   dev: same server, third database (`payment`), added via
   `db-init/create-payment-db.sh`. Same trade-off as booking's DB.

5. **What is the `EventBus` on the receiving side in Week 3?** A single
   `@Component EventBus` bean with a `publish(event)` method that just
   logs. Notification/analytics services don't exist yet. Phase 3 replaces
   this bean with an SNS-publishing adapter — outbox itself unchanged.

---

## 9. Interview questions (Weekend — answer FIRST)

Per the Week 2 pattern. **Write your answers in this file directly; don't
peek at the design sections above.**

1. Why is payment-service its own container instead of a `PaymentStub`
   class inside booking? Give three genuine reasons, not one.

   > _Your answer:_

2. Explain the dual-write problem in one paragraph. Then explain how
   outbox solves it, and what specific guarantee outbox provides (be
   precise — is it exactly-once? at-least-once? at-most-once?).

   > _Your answer:_

3. booking-service calls `POST /payments` and the network drops before
   response arrives. What are the possible actual states in payment-
   service? What must booking-service do — specifically — before it can
   safely proceed or rollback?

   > _Your answer:_

4. Auth vs capture — why does splitting them make the compensating path
   cleaner? Trace the three failure branches (auth-fail, capture-fail,
   confirm-fail) and show that only ONE branch actually needs a refund.

   > _Your answer:_

5. The recovery sweep filters out bookings younger than 2 minutes. What
   specific bug would happen without that filter?

   > _Your answer:_

6. Why is Adapter the right pattern for gateway integration, and Strategy
   the wrong one for the *same* concern? Name a real Strategy use inside
   payment-service where it does earn its cost.

   > _Your answer:_

7. Outbox gives at-least-once delivery. What contract does that force on
   every event consumer? Give a concrete example of how a naive consumer
   would break under this contract.

   > _Your answer:_

---

## 10. Day 1 Definition of Done

- [x] payment-service state machine defined (6 states, transition table, three-layer enforcement)
- [x] Adapter + Factory + Strategy discussed — chosen for the right concern each
- [x] Payment two-step (authorize + capture) explained and justified
- [x] API contract: `POST /payments`, `/capture`, `/void`, `/refund`, `GET /payments/{id}`
- [x] Outbox pattern explained end-to-end — table schema, publisher loop, guarantee (at-least-once), why-it-works walkthrough
- [x] Saga rollback failure matrix (5 rows) — including the in-doubt payment case and the refund case
- [x] Dangling recovery sweep design — pseudocode, age filter, idempotency argument
- [x] Directory layout for Week 3 committed on paper
- [x] Three sequence diagrams (happy with payment split, refund path, recovery from crash)
- [x] Open questions for Day 2 committed on paper (no surprises tomorrow)
- [x] 7 interview questions logged for Weekend review

Day 2 shuru → payment-service skeleton + Adapter + Factory + persistence.
