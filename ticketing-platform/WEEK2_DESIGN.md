# Week 2, Day 1 — Booking-service DESIGN (no code)

> Deliverable per `ROADMAP.md` §6, Day 1: state machine + service boundaries
> + saga-orchestration-vs-choreography decision + idempotency scheme + API
> contract + diagrams. **Zero code today.** Day 2 se code shuru.

---

## 1. Booking state machine

### States

| State | Meaning | Terminal? |
|---|---|---|
| `PENDING` | Row inserted; no downstream side-effect fired yet | no |
| `SEATS_HELD` | inventory `/hold` succeeded for every seat in the request; hold tokens saved | no |
| `PAYMENT_INITIATED` | Payment gateway called; awaiting result | no |
| `CONFIRMED` | Payment captured **AND** inventory `/confirm` succeeded for every seat | **yes** |
| `FAILED` | Some step failed; compensation ran (whatever was held is now released) | **yes** |
| `EXPIRED` | User abandoned mid-flow; hold TTL passed before payment; compensation ran | **yes** |

Terminal = no transitions out. This is the guarantee `EXPIRED → CONFIRMED` (interview Q7) will never happen — enforced at both the entity method level (a `Booking.confirm()` that throws on a terminal state) and via a DB check constraint that only allows non-terminal → next in the allowed set.

### Transition table

| From | Trigger | To | Notes |
|---|---|---|---|
| — | client `POST /bookings` | `PENDING` | Row inserted before any downstream call. If crash between insert and hold, `PENDING` is the recoverable marker. |
| `PENDING` | all inventory `/hold` OK | `SEATS_HELD` | Hold tokens stored per seat in `booking_seats` |
| `PENDING` | any `/hold` returns 409 / times out | `FAILED` | If some seats were held before the conflict, compensate = `/release` on those |
| `SEATS_HELD` | payment gateway called | `PAYMENT_INITIATED` | Set `payment_ref` before the call — if the call itself times out we still know we tried |
| `SEATS_HELD` | hold TTL elapses first | `EXPIRED` | Detected by the booking-side sweep; compensate = `/release` for any hold still live |
| `PAYMENT_INITIATED` | payment success **AND** all `/confirm` OK | `CONFIRMED` | The one happy terminal |
| `PAYMENT_INITIATED` | payment fails / times out | `FAILED` | Compensate = `/release` on every held seat |
| `PAYMENT_INITIATED` | payment OK but some `/confirm` fails | `FAILED` + **refund flag** | Money moved, seats aren't ours — needs refund. Flagged for op review. |
| Any terminal | anything | — | Rejected — throw `IllegalBookingTransitionException` mapped to 409 |

### Where transition validity is enforced

- **Layer 1 — entity method** (`Booking.markSeatsHeld()`, `.markConfirmed()`, etc.): reads current `status`, throws `IllegalBookingTransitionException` if invalid. This is the only place `status` gets written.
- **Layer 2 — DB check constraint** on `bookings.status` (enum) + a `check_valid_terminal` trigger that refuses any UPDATE that changes a terminal row's status. Defense against a rogue direct UPDATE (a manual fix, a future service that shouldn't be touching booking).
- **Layer 3 — `@Version`** (same pattern as `Seat`): a concurrent transition attempt loses the race cleanly.

Interview Q7 answered: `EXPIRED → CONFIRMED` blocked at all three layers — logic, storage, concurrency.

---

## 2. Service boundaries

```
┌──────────────────┐             ┌────────────────────┐
│ booking-service  │  REST call  │ inventory-service  │
│ (Booking owner)  │────────────►│  (Seat owner)      │
│                  │             │                    │
│  bookings table  │             │  seats table       │
│  booking_seats   │             │  hold:{id} (Redis) │
└──────────────────┘             └────────────────────┘
    ▲   │
    │   │  REST call
    │   ▼
┌──────────────────┐
│ payment-service  │
│  (stub, Wk 3)    │
└──────────────────┘
```

- **booking-service owns the `Booking` aggregate.** Nothing else writes `bookings`.
- **inventory-service owns `Seat` + hold.** booking-service **never** touches `seats` table directly — only via `POST /hold` and `POST /confirm`. Doing otherwise = two writers on one aggregate = the exact microservice anti-pattern the split was supposed to prevent.
- **inventory doesn't know booking exists.** It sees `holderId` strings (which now happen to be `booking-{uuid}`, but that's booking's business). This asymmetry keeps inventory reusable — a future admin tool could hold a seat too, no changes needed in inventory.
- **payment-service** stub only this week (200 + fake `payment_ref`). Real gateway wiring is Week 3.
- **Databases-per-service** — booking has its own Postgres schema, not a shared DB. Cross-service reads = REST, not JOIN.

### Cross-service data ownership rules

| Data | Owner | Everyone else reads via |
|---|---|---|
| Seat status | inventory | `GET /availability`, `POST /hold`, `POST /confirm` |
| Hold token | inventory (Redis) | included in `/hold` response |
| Booking status | booking | `GET /bookings/{id}` |
| Payment status | payment | `GET /payments/{ref}` (Week 3) |

---

## 3. Saga: orchestration chosen — the case

Roadmap §3 Phase 1 says "**orchestration** — kyun likh ke rakhna." Here it is:

### Why orchestration (booking-service = central coordinator)

1. **Single source of state.** One row (`bookings`) knows the whole flow. Debug = read one row + one service's logs. Trace, correlation ID, incident post-mortem — all trivially anchored.
2. **Complex conditional logic possible.** "Payment failed → release seats + optionally issue partial refund + email user + log for fraud analysis." This is a program, not a sequence of events. Programs live better in one place.
3. **Explicit compensation.** Each step has a paired compensate; the orchestrator knows what it did and what to undo.
4. **Bounded scope.** 3 services (inventory, payment, booking itself). Orchestration's coupling cost is low at this scale.
5. **Interview honesty:** ~90% of real-world payment/booking sagas in industry are orchestrated. Choreography sounds elegant, debugging it in production is not.

### Why NOT choreography (yet)

- Distributed state — the "current status" is inferred from an event stream, not read from a row. Great when true, brittle when reasoning under time pressure.
- Adding a new step requires touching every producer + every consumer, or a new subscriber that must be schema-compatible with an existing event.
- Compensation becomes "publish a `PaymentFailed` event and hope every affected service subscribes and does the right thing." Loose coupling and loose correctness are close cousins.

### When to revisit — pre-committing the trigger

Switch parts of the flow to choreography if any of these become true:
- A fan-out step naturally serves 4+ independent consumers (notification, analytics, loyalty, fraud, …) — orchestrator hard-wiring each one becomes a bottleneck.
- A step needs to happen genuinely in parallel and the orchestrator can't naturally express that.
- Two independent teams end up owning parts of the flow — an event contract is easier to co-own than an orchestrator's code path.

Until then: orchestration.

---

## 4. Compensating actions — every step named

| Step (forward) | Compensating action | Failure of the compensation itself |
|---|---|---|
| inventory `/hold` succeeds on 3 of 5 seats, 4th conflicts | `/release` on the 3 successful ones | Fire-and-forget log + reconciliation sweep picks up expired holds anyway (Week 1 already built) |
| payment fails after all seats held | `/release` on every held seat | Same as above — hold TTL is the ultimate safety net |
| payment OK but `/confirm` fails on 1 seat | **Refund needed.** Flag booking `FAILED` + `refund_pending=true`; op review | This is the honest hard case — no automated refund path this week, only detection + a queue for a human. Week 3 wires the refund path. |
| Client abandons after `SEATS_HELD` | Sweep detects hold TTL expiry → `/release` (harmless if already released) + `EXPIRED` | (No mid-flow write to compensate) |

**Design rule:** compensations are idempotent. `/release` is already idempotent (Week 1). Retrying a compensation must never make things worse.

---

## 5. Idempotency-Key — end-to-end

### Client contract
- Client generates a UUID per booking attempt, sends `Idempotency-Key: <uuid>` header.
- Same key + same body within the retention window = **same booking returned** (200, not 201).
- Same key + **different body** within the window = **422 Unprocessable Entity** ("this key already means a different booking"). Prevents accidental key reuse from silently succeeding.
- No key = 400 Bad Request. The endpoint refuses to be non-idempotent.

### Where it lives
- Column `idempotency_key VARCHAR(64) NOT NULL UNIQUE` on `bookings` itself. Not a separate `idempotency_keys` table.
- **Why on the row, not a separate table:** the key IS the booking's identity from the client's point of view. A separate table is one more write + one more thing that can race with the booking insert. The row + unique index does both jobs in one insert.
- A hash of the canonical request body (`request_hash`) sits alongside — checked when a dup key comes in, drives the 422 branch.

### Retention
- Keep the key on the row forever (it's tiny, and the booking itself is durable). No TTL cleanup job.
- Contrast: DynamoDB idempotency store (Phase 4 / Week 9) uses a TTL of 24h because that store handles cross-service dedup — different concern, different lifetime.

### Racing insert
- Two parallel `POST /bookings` with the same key: one wins the unique index, the other catches `DataIntegrityViolationException`, re-reads by key, returns the existing booking. `@Version` on `bookings` is still there for concurrent status writes later in the flow.

Interview Q3 answered.

---

## 6. API contract

### `POST /bookings`

**Headers**
- `Idempotency-Key: <uuid>` — **required**
- `X-Correlation-Id: <uuid>` — optional; generated if absent (same filter as Week 1)
- `Content-Type: application/json`

**Body**
```json
{
  "showId": 1,
  "seatIds": [5, 6, 7],
  "holderId": "user-42"
}
```

**Validation** (`jakarta.validation`): `showId` not null + positive; `seatIds` non-empty + max 6; `holderId` not blank.

**Responses**

| Status | When | Body |
|---|---|---|
| **201 Created** | Fresh happy path | `BookingResponse` (below) |
| **200 OK** | Same key + same body (idempotent retry) | same `BookingResponse` |
| **400 Bad Request** | Missing header, validation error | `ProblemDetail` with `errors` map |
| **409 Conflict** | Any seat unavailable | `ProblemDetail` with `unavailableSeats: []` |
| **422 Unprocessable Entity** | Key reused with different body | `ProblemDetail` explaining the key clash |
| **502 Bad Gateway** | Inventory/payment unreachable after retries | `ProblemDetail`; booking in `FAILED` with compensation done |
| **504 Gateway Timeout** | Inventory/payment call timed out | `ProblemDetail`; booking `FAILED` or `PENDING` (recovery sweep) |

**`BookingResponse`**
```json
{
  "bookingId": 101,
  "status": "CONFIRMED",
  "showId": 1,
  "seatIds": [5, 6, 7],
  "holderId": "user-42",
  "paymentRef": "pay-stub-xyz",
  "createdAt": "2026-09-18T09:15:00Z",
  "confirmedAt": "2026-09-18T09:15:02Z"
}
```
Note: `status` is included so the client can distinguish `CONFIRMED` from an intermediate state a recovery sweep would move forward. `version` is deliberately **not** exposed (same rule as `SeatResponse`).

### `GET /bookings/{id}`

**Responses**

| Status | When | Body |
|---|---|---|
| 200 | Found | `BookingResponse` |
| 404 | Not found | `ProblemDetail` |

No listing endpoint this week — a real one needs pagination + filters + auth, which is out of scope. Deliberate omission.

---

## 7. Sequence diagrams

### Happy path
```
Client            booking-svc          inventory-svc         payment-svc
  │  POST /bookings    │                    │                    │
  │───────────────────►│                    │                    │
  │                    │  INSERT booking    │                    │
  │                    │  status=PENDING    │                    │
  │                    │  (Idempotency-Key  │                    │
  │                    │   unique index)    │                    │
  │                    │                    │                    │
  │                    │  POST /hold (×N)   │                    │
  │                    │───────────────────►│                    │
  │                    │◄───200 hold tokens─│                    │
  │                    │  UPDATE booking    │                    │
  │                    │  status=SEATS_HELD │                    │
  │                    │                    │                    │
  │                    │  POST /charge      │                    │
  │                    │────────────────────────────────────────►│
  │                    │  status=PAYMENT_INITIATED               │
  │                    │◄──────────────────────200 payment_ref───│
  │                    │                    │                    │
  │                    │  POST /confirm (×N)│                    │
  │                    │───────────────────►│                    │
  │                    │◄───200─────────────│                    │
  │                    │  UPDATE booking    │                    │
  │                    │  status=CONFIRMED  │                    │
  │◄───201 BookingResponse                  │                    │
```

### Payment-fail rollback
```
Client            booking-svc          inventory-svc         payment-svc
  │  POST /bookings    │                    │                    │
  │───────────────────►│                    │                    │
  │                    │  status=PENDING    │                    │
  │                    │  /hold ✔ (all)     │                    │
  │                    │───────────────────►│                    │
  │                    │◄───200─────────────│                    │
  │                    │  status=SEATS_HELD │                    │
  │                    │  /charge ✘         │                    │
  │                    │────────────────────────────────────────►│
  │                    │◄───500 / timeout────────────────────────│
  │                    │  status=PAYMENT_INITIATED (already set) │
  │                    │  → compensate:      │                    │
  │                    │  /release (×N)     │                    │
  │                    │───────────────────►│                    │
  │                    │◄───204─────────────│                    │
  │                    │  status=FAILED     │                    │
  │◄───502 ProblemDetail                    │                    │
```

The `/release` calls are idempotent (Week 1 guarantee) — retrying compensation is safe.

### Idempotent retry (response lost)
```
Client            booking-svc          inventory-svc         payment-svc
  │  POST (key K)      │  (as happy path, ends in CONFIRMED)     │
  │───────────────────►│  ...                                    │
  │  ✘ response lost   │                    │                    │
  │                    │                    │                    │
  │  POST (key K)  ← retry                  │                    │
  │───────────────────►│                    │                    │
  │                    │  SELECT WHERE key=K│                    │
  │                    │  → existing row    │                    │
  │                    │  hash matches?     │                    │
  │                    │  yes → return it   │                    │
  │◄───200 same BookingResponse             │                    │
```

---

## 8. Open questions — decide before Day 2

Small list of things the design left un-nailed on purpose, because Day 2's first line of code will force the answer:

1. **Recovery sweep for `PENDING`/`SEATS_HELD`/`PAYMENT_INITIATED` on crash mid-saga** — is this Day 3 (with the happy path) or Day 5 (as a failure experiment)? Leaning Day 5, since Day 3's goal is the happy end-to-end and a sweep needs its own tests.
2. **Payment stub** — in booking-service (a `PaymentStubClient`) or a real `payment-service` container from Day 1? Roadmap §6 Day 3 says "payment stub success", not a separate service — so **stub inside booking-service** first, split into a real `payment-service` Week 3.
3. **Multi-seat holds** — inventory currently exposes `/hold` per single seat. Loop-with-compensation in booking, or add a `/hold-batch` to inventory this week? **Loop for now**, don't broaden inventory's contract mid-flight; batch is a Week 3 optimization if the loop's failure math turns out ugly.
4. **Booking-side "who owns a hold" bridge** — `booking_seats` will store `(booking_id, seat_id, hold_token, released_at)`. Confirms compensation is targeted (release only what we actually held), not blanket.

---

## 9. Interview questions (Weekend — answer before evaluation)

Per roadmap §6 Weekend. **Write your answers in this file directly; don't peek at the design sections above first.**

1. Booking flow ke liye orchestration vs choreography saga — kaunsa aur kyun?

   > _Your answer:_

2. Seat hold ho gaya but payment fail — exactly kya compensate, aur agar compensation bhi fail?

   > _Your answer:_

3. Idempotency-Key kahan store, kab tak valid, uniqueness kis field pe?

   > _Your answer:_

4. Booking crash — seat HELD, CONFIRMED nahi. Recovery strategy? (dangling saga)

   > _Your answer:_

5. Sync REST booking→inventory ka core problem? Async kab justify?

   > _Your answer:_

6. 2PC kyun avoid ticketing mein?

   > _Your answer:_

7. `EXPIRED` booking ko `CONFIRMED` hone se kaise roko — kis layer pe?

   > _Your answer:_

---

## 10. Day 1 Definition of Done

- [x] State machine defined — states, transitions, invalid transitions, enforcement layers
- [x] Service boundaries drawn — booking never touches `seats` directly
- [x] Orchestration chosen with written justification + revisit-triggers
- [x] Compensating actions named for every forward step (including double-failure)
- [x] Idempotency-Key scheme end-to-end (client contract + storage + retention + race)
- [x] API contract: `POST /bookings`, `GET /bookings/{id}` — request/response/error shapes
- [x] Sequence diagrams: happy, payment-fail rollback, idempotent retry
- [x] Open questions for Day 2 committed on paper (no surprises tomorrow)

Day 2 shuru → skeleton + persistence + idempotency-key insert.
