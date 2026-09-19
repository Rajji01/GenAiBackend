# Ticketing Platform — Learning Notes

Prose-style deep revision notes for the ticketing track. Companion to the
HTML notes (`SEAT_LOCK.html` for Week 1, `SAGA_LAB.html` for Week 2). The
HTMLs are showcase artifacts — this file is the study guide, with
self-check questions at the end of each section. **Answers are not
given by design; that's what makes it a revision tool.**

Same format as `narration-enrichment/LEARNING_NOTES.md` (the Python track's
equivalent).

---

## Table of contents

- [Week 1 recap — inventory-service](#week-1-recap--inventory-service)
- [Week 2 — booking-service and the saga](#week-2--booking-service-and-the-saga)
- [Cross-cutting concepts worth mastering](#cross-cutting-concepts-worth-mastering)

---

## Week 1 recap — inventory-service

The concurrency-safe seat-hold service. Full deep notes live in
`SEAT_LOCK.html`; this section is a study-guide-density recap.

### The scenario that shapes everything

Two people tap "Book" on the same seat at the same instant. Exactly one
must win. The other must see a clean 409, not a crash, not a double-book.
Also: the winner's hold must auto-expire if they never pay, and the
system must handle that expiry even if the naive path forgets to.

### Two stores, two lifetimes

Postgres owns the durable `seats` row (source of truth for what exists,
what's booked). Redis owns the ephemeral `hold:{seatId}` key with a
5-minute TTL — a hold is intentionally *not* durable, because a Redis
restart losing an in-flight hold should FREE the seat, not strand it.
That's why the compose file gives Postgres a volume and gives Redis none.

### The two-tier concurrency defense

- **Redis SETNX with TTL** is the fast, atomic, single-threaded server-
  side mutual-exclusion primitive. In the normal flow, this is what
  actually resolves the race — one caller's SETNX wins, the other gets a
  clean conflict before Postgres is even touched.
- **Postgres `@Version`** is the independent SQL-level backstop for any
  path that skips Redis (a future service, an admin fix, a bug in the
  Redis check). Hibernate turns it into `WHERE id=? AND version=?` on
  every UPDATE — a concurrent writer that read the same row first fails
  cleanly, no silent overwrite.

Neither store is trusted alone.

### Self-heal via reconciliation

`HoldReconciliationService` runs a `@Scheduled` sweep — finds Postgres
rows where `status = HELD` but the Redis key has expired, flips them
back to `AVAILABLE`. Polling was chosen over Redis keyspace notifications
because a pub/sub event fired during an app restart is lost forever, and
that would leak a seat stuck HELD with no recovery. A periodic sweep
self-heals even after a missed event.

### Confirm and the afterCommit fix

`POST .../confirm` moves a seat from `HELD` to `BOOKED`, standing in for
a payment-success callback. The interesting engineering: the Redis key
delete is registered in an `afterCommit` callback, NOT immediately after
`saveAndFlush`. Otherwise, a commit failure would leave the seat rolled
back to `HELD` with the Redis key already gone — reconciliation would
then free it and the booking would be silently lost.

### Self-check questions — Week 1

1. Why is Redis's volume deliberately missing in `docker-compose.yml`?
   What would happen if it were added?
2. Explain how `@Version` prevents overselling at the SQL level. Write
   the actual SQL Hibernate sends on a hold.
3. In the normal `hold()` flow, Redis SETNX decides the race. So why
   keep `@Version` at all? Name one real path that skips Redis.
4. Redis keyspace notifications COULD be used to detect TTL expiry
   instantly. Why did we pick a polling sweep instead? What would break
   with pub/sub?
5. `confirm()` uses `afterCommit` for the Redis delete. Walk through
   what goes wrong step by step if it were deleted immediately after
   `saveAndFlush`.
6. How does `hold()` remain idempotent under a client retry?

---

## Week 2 — booking-service and the saga

Where "one service correctly" becomes "several services that stay
correct *together*."

### The problem the saga exists to solve

A booking spans three owners: seats (inventory-service), money (payment-
service, stubbed for now), and the booking record itself. Each of those
lives in a different database (or gateway). A single database
transaction cannot span them — so instead of pretending atomicity, we
build a **saga**: a sequence of local transactions, each with a named
compensating action, orchestrated centrally.

### Why orchestration, not choreography

Both are valid saga styles. We chose orchestration (a coordinator drives
the sequence and knows the state) over choreography (services react to
each other's events, no coordinator). Reasons:

- Complex conditional logic ("payment OK but confirm fails → refund
  flag + ops queue") lives cleanly in one place.
- One row = the whole story. Debug = read one row + one service's logs.
- Bounded scope (3 services). Orchestration's coupling cost is low here.
- Industry reality: ~90% of real payment/booking sagas are orchestrated.
  Choreography sounds elegant; production debugging it isn't.

Pre-committed revisit trigger: switch parts of the flow to choreography
when a step naturally serves 4+ independent consumers.

### The state machine, enforced three ways

```
PENDING → SEATS_HELD → PAYMENT_INITIATED → CONFIRMED (terminal, happy)
     ↘                                    ↗
      → FAILED (terminal, compensated)
      → EXPIRED (terminal, TTL passed)
```

Invalid transitions (e.g. `EXPIRED → CONFIRMED`) are blocked in three
places so no single layer being wrong loses the guarantee:

1. **Entity method:** `markConfirmed()` validates the current status,
   throws `IllegalStateException` on a wrong one.
2. **DB check constraint** (planned): raw SQL `UPDATE` on a terminal
   row is refused.
3. **`@Version`:** concurrent status writes — only the first commits.

### Idempotency-Key — client-supplied, DB-enforced

Every `POST /bookings` MUST carry an `Idempotency-Key` header. The
endpoint *refuses to be non-idempotent* — no key = 400. Same key + same
body = same booking returned. Same key + different body = 422.

The key lives on the `bookings` row itself with a UNIQUE constraint —
not a separate `idempotency_keys` table, because the key IS the
booking's client-side identity. One INSERT does both jobs.

**Canonical hash** of the request body (sorted seatIds + fixed field
order → SHA-256) handles the "same intent, reordered" case without a
false-firing 422.

### The Day 2 bug and the REQUIRES_NEW fix

Concurrent-insert race test failed with a confusing
`AssertionFailure: null id`. Root cause: catching a constraint violation
in the SAME transaction and continuing (re-read the winning row) is
unsafe — Hibernate poisons the session at the moment of the flush
failure. Fix: put the insert in its own `TransactionTemplate` with
`PROPAGATION_REQUIRES_NEW`. The failed insert's transaction rolls back
in isolation; the outer flow re-reads on a healthy session.

**Same class of trap** applied later to the saga: every state transition
runs in its own `TransactionTemplate(REQUIRES_NEW)`, NOT `@Transactional`
on same-bean private methods (Spring's proxy silently bypasses those).

### Resilience4j — three tools, three concerns

One outgoing HTTP call can fail three genuinely different ways:

- **Blip** (2s downtime, GC pause) → **Retry** absorbs it.
- **Persistent outage** (5min down) → **Circuit Breaker** opens, fails
  subsequent calls fast, keeps threads alive.
- **Slow response** (network lag) → **Timeout** caps each attempt.

The retry policy is expressed as an **exception hierarchy**:
`InventoryTransientException extends InventoryClientException`. Config
whitelists the subclass for retry, blacklists the base. New exception
subtype's default = ignore, which is the safe posture.

Fallback method throws instead of degrading — booking cannot invent a
seat hold; silent success under a broken dependency would be a silent
oversell.

### Docker Compose — the multi-service networking basics

- Inside the compose network, hostnames are service names. Booking
  reaches inventory as `http://inventory-service:8081`. `localhost`
  loops back to booking's own container — a classic first-time trap.
- Two Postgres databases on ONE Postgres server in local dev — the
  invariant "no cross-service JOINs" is what matters, not physical
  separation. Real AWS makes them separate RDS instances, changing
  only env vars.
- **`condition: service_started`, NOT `service_healthy`** for booking
  → inventory: startup coupling defeats microservices; runtime
  resilience (Resilience4j) is how downstream unavailability is handled.

### Self-check questions — Week 2

1. Given orchestration vs choreography, why did we pick orchestration
   for THIS specific booking flow? Name the pre-committed trigger to
   revisit that decision.
2. Explain in your own words why a `@Transactional` on a private method
   called from the same bean does nothing. What's the visible symptom?
3. Walk through the concurrent-insert race scenario for two identical
   `POST /bookings` requests with the same fresh key. Where does the
   race resolve? What does the loser return?
4. Why is `InventoryTransientException` a subclass of
   `InventoryClientException`, not a sibling? What does that buy?
5. A CircuitBreaker fallback returns a graceful `HoldResponse(seatId,
   holderId="", ttl=0)` instead of throwing. What real-world bug does
   this cause? Trace it through the saga.
6. `docker-compose.yml` uses `condition: service_started` for booking →
   inventory. Someone changes it to `service_healthy`. What breaks?
   What worked before?
7. Two Postgres databases share one server here. Under what conditions
   does that stop being acceptable? What's the migration cost when it
   does?
8. `Idempotency-Key` reuse with a different body returns 422 (not 409).
   Why? Which HTTP status truly fits, and what does the semantic
   difference mean for a client?
9. Every state transition in the saga uses `TransactionTemplate` with
   `REQUIRES_NEW`. What would happen if we used the default propagation
   (`REQUIRED`) instead?
10. A booking is currently `PAYMENT_INITIATED`. The confirm call fails
    on one of three seats. What does the saga do? What's the difference
    from a payment failure that this branch has?

---

## Cross-cutting concepts worth mastering

These aren't tied to a single week — they're the primitives you'll
reach for again in every phase of this track.

### RFC 7807 `ProblemDetail`

Machine-parseable error responses with a stable shape:
`{ type, title, status, detail, instance, ...custom }`. Both services
use it via `GlobalExceptionHandler` (deliberately copied, not extracted
into a shared lib — a shared lib would couple deploy cycles for a class
of change that should stay independent).

### MDC + correlation IDs

`X-Correlation-Id` header (incoming, or generated). Written to SLF4J
MDC for the request's lifetime, cleared in `finally` (Tomcat worker
thread reuse would otherwise leak IDs across requests). Forwarded on
outgoing calls so a single grep across both services' logs reads as
one story.

### Testcontainers over fakes

Every test uses real Postgres (and, for inventory, real Redis) via
Testcontainers. H2 dialect would hide the exact concurrency and
constraint-violation bugs these projects exist to prevent. Same
discipline in Week 1 as Week 2 as narration-enrichment (Python side).

### The "boundary" principle for mocking

When you MUST mock, mock at the real boundary — the HTTP call, the
external SDK's exposed method — not one layer higher inside your own
code. Higher-level mocks produce unrealistic exception shapes, hide
integration bugs, and lie about what actual failures look like. The
Day 2 bug (concurrent-insert race) was invisible until we tested
against a real Postgres because the fake wouldn't throw a real
`DataIntegrityViolationException`.

### Design-first (WEEK2_DESIGN.md) before code

Distributed workflows have too many ways to be almost-right. Writing
the state machine + service boundaries + compensations + API contract
BEFORE the first line of code prevents Day 2's first line from
inventing decisions Day 5 will have to unwind.

### Interview-facing self-check

Before starting Week N+1, answer that week's interview questions IN
WRITING first (WEEK1_REVIEW.md, WEEK2_DESIGN.md §9). Then have them
evaluated. This is what turns "I built X" into "I can explain X well
enough to defend the design under adversarial questioning" — the
actual bar interviews test.

---

*Weeks 1 + 2 covered. Update this file at the end of each new week.*
