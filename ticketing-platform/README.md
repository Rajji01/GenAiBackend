# ticketing-platform

A District/BookMyShow-style event ticketing & seat-booking system, built as
5-7 microservices, introduced gradually. Full phase map and rationale live
in `Jarvis_Architect_Path.md` one level up — this README only covers what
exists so far: **Phase 0 / Week 1 — `inventory-service`**.

The soul of this project is **concurrency + overselling prevention**: 500
people can watch the same seat, but exactly one of them gets it, a failed
payment auto-frees it, and nothing ever double-books. Everything else
(AWS services, other microservices, messaging) is introduced only when
`inventory-service` genuinely needs it — never "because it exists."

## Week 1 goal

`inventory-service` running locally, senior-grade, with
**concurrency-safe seat holds**. Oversell impossible. One service, done
excellently, before Phase 1 adds anything else.

## Seat / hold data model (Day 1 design)

Two different stores for two different lifetimes, on purpose:

- **Postgres — `Seat`** (durable, source of truth for what exists):
  `id`, `show_id`, `seat_number`, `status` (`AVAILABLE` / `HELD` /
  `BOOKED`), `version` (optimistic-lock column, `@Version`). A seat's
  *existence* and its *confirmed* state must survive a restart — this is
  not something that's ever allowed to just disappear.
- **Redis — hold token** (ephemeral, meant to expire): key
  `hold:{seatId}`, value = a hold token / user reference, **TTL 5
  minutes**. A hold is deliberately *not* durable — if Redis restarts and
  loses an in-flight hold, the correct behavior is "seat becomes
  available again," not "seat is stuck." That's why `docker-compose.yml`
  gives Postgres a volume and gives Redis none — the missing volume is
  the design decision, not an oversight.

## Hold → confirm flow (the money flow this proves)

```
Client                 inventory-service              Postgres        Redis
  │  POST /hold               │                            │             │
  │──────────────────────────►│                            │             │
  │                            │  SETNX hold:{seatId} TTL=5m │             │
  │                            │───────────────────────────────────────►│
  │                            │        already held? ──────────────────│
  │                            │◄───────────────────────────────────────│
  │                            │  if free: UPDATE seat SET status=HELD  │
  │                            │  WHERE id=? AND version=?  (optimistic) │
  │                            │───────────────────────────►│             │
  │                            │  version mismatch = someone else won it│
  │  200 {holdToken}  or  409  │◄───────────────────────────│             │
  │◄──────────────────────────│                            │             │
```

Two concurrent holds on the *same* seat: exactly one succeeds with 200,
the other gets a clean `409 Conflict` from the version mismatch — never a
crash, never both succeeding. This is Day 5's failure experiment, and
it's the thing to actually demonstrate in an interview, not just describe.

If the holder never pays, the Redis key's TTL expires on its own — no
cleanup job needed for the common case. (What happens to the Postgres
`HELD` row when that happens is a real open question for Day 3 — a naive
version would need a reconciliation path so a seat doesn't stay `HELD`
forever just because Redis alone expired.)

`POST /shows/{showId}/seats/{seatId}/confirm` represents the already-successful
payment callback for this phase. Only the current hold owner can confirm; it
durably transitions `HELD` to `BOOKED`, records that owner for safe duplicate
callbacks, and removes the temporary Redis key. Payment processing itself is
deliberately not invented inside inventory-service yet: that becomes a separate
boundary when a payment service is introduced.

## Run locally

Everything, one command (Day 4 — Postgres, Redis, and the service itself):

```bash
cp .env.example .env
docker compose up --build
curl http://localhost:8081/actuator/health
```

Or, for a faster inner dev loop while iterating on the service (rebuild +
restart via `./mvnw` instead of a Docker image rebuild each time):

```bash
cp .env.example .env
docker compose up -d postgres redis
cd inventory-service
./mvnw spring-boot:run
```

## Test

```bash
cd inventory-service
./mvnw test
```

Uses Testcontainers for both Postgres and Redis in the test suite —
deliberately not H2 or an embedded Redis fake. The entire point of Week 1
is proving real concurrency behavior; a convenience substitute could
easily hide the exact race condition this project exists to prevent.

## Day-by-day log

- **Day 1** — read `Jarvis_Architect_Path.md`, designed the seat/hold data
  model and the hold→confirm flow above, and stood up the repo skeleton:
  Maven/Spring Boot 3.4.3 project, `docker-compose.yml` (Postgres +
  Redis, Postgres volume-backed / Redis intentionally not), `.env.example`,
  and a Testcontainers-backed context-load test proving the skeleton
  boots against real Postgres + Redis before any entity code exists.
- **Day 2** — `Seat` entity (`@Version`, unique `(show_id, seat_number)`
  constraint), `SeatRepository`, `SeatService`, and
  `GET /shows/{showId}/seats/availability`, following the exact
  controller/service/repository/dto layering already used in
  `GenAiBackend/backend`. A `SeatSeedConfig` (same pattern as that
  project's `ProductSeedConfig`) seeds 10 demo seats for show 1 on
  startup, standing in for catalog-service until Phase 2. Verified live
  with 7 tests: a `@DataJpaTest` + Testcontainers-Postgres suite
  (`replace = NONE`, so it can't silently fall back to H2) covering
  show-scoped queries, the unique constraint, and that a new seat gets a
  version assigned on insert; a `@WebMvcTest` slice proving the
  `/availability` response never leaks the internal `version` field.
  Deliberately did **not** try to prove optimistic-lock failure here —
  within one JPA persistence context, two `findById()` calls for the
  same row return the *same* managed instance, so there's no staleness
  to reproduce without real concurrency. That proof is Day 5's job.
- **Day 3** — `HoldService`: `POST /hold` and `POST /release`, backed by
  Redis (`SETNX ... EX 300` via `StringRedisTemplate.setIfAbsent`) *and*
  Postgres's `@Version` together — neither store is trusted alone. Redis
  is the fast TTL-backed mutual-exclusion check that lets an abandoned
  hold self-heal with no cleanup job; Postgres's optimistic lock is the
  actual correctness guarantee, since Redis alone can't protect the seat
  row from an unrelated write path. If the Postgres step fails after
  Redis already granted the key, the key is deleted as a compensating
  action — a Redis lock must never outlive the Postgres state it was
  supposed to protect. Hold is idempotent for retries by the same
  `holderId` (LLD requirement); release is idempotent by design (no
  active hold is a no-op, not an error) and refuses to un-book a seat
  that became `BOOKED` while it was held. Global exception handling
  (`GlobalExceptionHandler`, RFC 7807 `ProblemDetail`) added, matching
  `GenAiBackend/backend`'s exact pattern: `ResourceNotFoundException`→404,
  `ConflictException`→409, `ForbiddenException`→403 (new — distinct from
  409: the resource is fine, you just don't hold it),
  `OptimisticLockingFailureException`→409. Also closes a gap this README
  flagged as open back on Day 1: `HoldReconciliationService` runs a
  `@Scheduled` sweep (polling, deliberately not Redis keyspace-notification
  pub/sub — a missed pub/sub event during an app restart would leak a
  seat stuck `HELD` forever, a periodic sweep self-heals even after a
  missed one) that finds `HELD` seats whose Redis key has already expired
  and reverts them, so the Week 1 DoD line "Redis TTL hold expires
  correctly (seat free)" is actually true, not just "the Redis key is
  gone." 26 tests total now — 10 new in `HoldServiceTest` against real
  Postgres **and** Redis together (the one place a fake of either store
  would hide the exact coordination bug this class exists to prevent), 6
  new in a `HoldControllerTest` slice for the HTTP/exception-mapping
  contract, 3 new in `HoldReconciliationServiceTest`.
  Two real bugs surfaced live while building this, both honestly worth
  recording: (1) adding `@Scheduled` meant every `@SpringBootTest` in the
  suite now had a live background scheduler that could fire after that
  test class's own Testcontainers were already torn down — caught as a
  "Connection refused" error in an otherwise-passing run; fixed by gating
  the reconciliation bean behind `inventory.reconciliation.enabled`,
  off by default in tests, re-enabled only where a test actually needs
  it. (2) the first fix attempt used a `src/test/resources/application.yml`
  to set that one property — same filename as the main config, which
  Spring Boot resolves to exactly *one* classpath resource, so it
  silently replaced the whole main config instead of layering onto it
  (`ddl-auto` and everything else vanished, breaking tests that had
  nothing to do with reconciliation). Fixed by using a profile-specific
  `application-test.yml` + `@ActiveProfiles("test")` instead, which
  correctly merges. A stale copy of the first, wrong file lingering in
  `target/test-classes/` after a non-clean rebuild reproduced the same
  failure a third time before `mvn clean test` cleared it — a reminder
  that "it's fixed in source" isn't the same as "it's fixed on disk."
- **Day 4** — `CorrelationIdFilter` fills in the `%X{correlationId:-none}`
  slot the logging pattern has shown since Day 1: reuses an incoming
  `X-Correlation-Id` header if present, generates one otherwise, puts it
  in MDC for the life of the request, and clears it in a `finally` (Tomcat
  reuses worker threads across requests — leaving it set would leak one
  request's id into the next one on the same thread). `InventoryProperties`
  (`@ConfigurationProperties`) replaces the hardcoded 5-minute hold TTL
  constant with `inventory.hold.ttl-seconds` — deliberately scoped to just
  that value, since reconciliation's `enabled`/`interval-ms` are read by
  `@ConditionalOnProperty`/`@Scheduled` directly (framework annotations
  evaluated before any properties bean exists to inject; wrapping them in
  `InventoryProperties` too would just be a second, unused way to read
  the same property). Actuator added, `/actuator/health` only exposed
  (not the full surface — no auth in front of it yet). Closes the Week 1
  DoD line "Docker Compose up → sab chalta hai ek command se" for real:
  a multi-stage `Dockerfile` (dependency layer cached separately from app
  code, same principle as narration-enrichment's) and `inventory-service`
  added to `docker-compose.yml`, `depends_on: condition: service_healthy`
  on both Postgres and Redis, healthchecked itself via
  `wget .../actuator/health`. Verified live: `docker compose up --build`
  brings up all three containers from cold with no separate `mvnw` step.
  30 tests total — 4 new in `CorrelationIdFilterTest` (MDC set during the
  chain, cleared after, cleared even when the chain throws).
- **Day 5 — the failure experiment, made repeatable, then done live too.**
  `ConcurrentHoldFailureExperimentTest` fires two real threads at the same
  seat with a `CountDownLatch` forcing them to start together, twice:
  once through the full `HoldService.hold()` flow (proving the end-to-end
  behavior), once bypassing Redis entirely and racing two threads directly
  against `SeatRepository.save()` (proving Postgres's `@Version` alone,
  independent of Redis — Day 2 explicitly deferred this exact proof since
  it needs real threads, not sequential reads in one persistence context).
  **A genuinely useful, honest finding from writing this:** in the normal
  `/hold` flow, Redis's single-threaded `SETNX` is what actually resolves
  the race in practice — one caller's key-set wins, the other gets a
  `ConflictException` before Postgres is ever touched. Postgres's
  `@Version` check is the independent, always-on safety net for any path
  that reaches it (a future service, a manual fix, a bug in the Redis
  check) — not a redundant no-op, since the second test above proves it
  holds *even with Redis completely out of the picture*.

  Then verified live, exactly as the plan asked ("2 curl in parallel"),
  against a really running instance (`docker compose up -d postgres
  redis` + `./mvnw spring-boot:run`, avoiding the heavier full container
  build this run):
  ```
  $ curl -X POST http://localhost:8081/shows/1/seats/1/hold -d '{"holderId":"user-A"}' &
  $ curl -X POST http://localhost:8081/shows/1/seats/1/hold -d '{"holderId":"user-B"}' &

  user-A -> 409 {"title":"Conflict","detail":"Seat 1 is already held by someone else"}
  user-B -> 200 {"seatId":1,"holderId":"user-B","ttlSeconds":300}
  ```
  The app's own logs for that exact pair of requests carry two different
  correlation IDs (Day 4's filter, confirmed working under real concurrent
  load, not just in its own unit test) — `90d9697e...` for the rejected
  attempt, `c164c84a...` for the granted one. `GET /shows/1/seats/availability`
  afterward confirms seat 1 as `HELD` — not a crash, not a double-hold,
  exactly one winner.
- **Weekend — `confirm`, closing the hold lifecycle.** `POST .../confirm`
  moves a seat from `HELD` to `BOOKED`, standing in for the future
  booking-service saga's "payment succeeded" step. Only the live Redis
  hold owner can confirm (`403` for anyone else, `409` if the hold already
  expired). The owner is written to Postgres (`booked_by_holder_id`)
  because the Redis key is deleted at confirmation — so a retried
  callback (response lost after commit) is recognized from the durable
  row and gets the same `200`, while anyone else gets `409`. A failed
  Redis cleanup after the Postgres write is only logged: the stale key
  expires on its own, reconciliation only frees `HELD` seats, and release
  never un-books. 40 tests total — 8 new: 6 in `HoldServiceTest` (happy
  path, idempotent retry, wrong holder, no hold, hold expired before the
  reconciliation sweep, seat already booked by someone else) and 2 in
  `HoldControllerTest`.
  **Known trade-off, not fixed yet:** the Redis key is deleted after
  `saveAndFlush` but *before* the transaction commits. If the commit
  itself failed after that, the seat would stay `HELD` with no key and
  reconciliation would free it. `@Version` still prevents a double
  booking, so this is a lost booking, not an oversell. The clean fix is
  to delete the key in an `afterCommit` callback.

## Week 2 — `booking-service` (in progress)

Week 2 introduces the second service on this track: `booking-service`, the
saga orchestrator. Full daily plan lives in `ROADMAP.md` §6; day-by-day
state so far:

- **Day 1 — Design (no code).** `WEEK2_DESIGN.md`: booking state machine
  (6 states, invalid transitions blocked at 3 layers), service
  boundaries (booking never touches `seats` directly), orchestration-vs-
  choreography decision with the trigger to revisit pre-committed,
  compensating actions named for every forward step (including the hard
  "payment OK but confirm fails" refund case), idempotency-key end-to-
  end, `POST /bookings` + `GET /bookings/{id}` API contract, 3 sequence
  diagrams (happy, rollback, idempotent retry), and 7 interview
  questions for the Weekend review.
- **Day 3 — Saga wiring, in-process happy + rollback paths.** New:
  `InventoryClient` (Spring `RestClient`, wraps `/hold` + `/confirm` +
  `/release`, forwards `X-Correlation-Id` on every outgoing call),
  `PaymentStub` (always-success unless `booking.payment.simulate-failure`
  is set), `BookingSagaService` (state machine driver:
  `PENDING → SEATS_HELD → PAYMENT_INITIATED → CONFIRMED` on success;
  compensating `/release` + `FAILED` on any downstream failure). State
  transitions on `Booking` are named methods that validate the current
  state — a raw `setStatus()` is unreachable, matching the three-layer
  enforcement in `WEEK2_DESIGN.md §1`. `SagaFailedException` → 502 Bad
  Gateway with `bookingId` in the ProblemDetail. **Every state transition
  runs in its own `TransactionTemplate` (`PROPAGATION_REQUIRES_NEW`)**
  rather than `@Transactional` on same-bean methods (silent proxy bypass
  is the exact class of foot-gun Day 2's bug #3 caught) — the whole saga
  is a sequence of small independently-committed steps, which is exactly
  what a saga is supposed to be. 26 tests total (5 new
  `BookingSagaServiceTest` cases: happy path, hold-conflict on 1st seat
  vs 2nd seat, payment-fail rollback, release-during-compensation-itself-
  fails). Inventory + payment mocked; DB is real Postgres via
  Testcontainers. **Deferred to a follow-up pass:** Resilience4j on the
  outgoing calls (timeout/retry/circuit breaker); real cross-service
  HTTP is Day 4's docker-compose integration.

- **Day 2 — Skeleton + persistence + idempotency.** New Maven module
  `booking-service/` (Spring Boot 3.4.3, Java 17, own Postgres database
  on the same server as inventory's). `Booking` + `BookingSeat`
  entities, `BookingStatus` enum, `@Version`, unique index on
  `idempotency_key`. Reused `GlobalExceptionHandler` (RFC 7807) and
  `CorrelationIdFilter` — **deliberately copied, not extracted into a
  shared library** (shared libs across services couple deploy cycles
  for a class of change that should stay independent). 21 tests, all
  against real Postgres via Testcontainers. Every booking created on
  Day 2 stops at `PENDING` on purpose — the saga arrives Day 3.
  **Three real bugs caught live** during Day 2, all documented in
  `SAGA_LAB.html` §Bug museum: (1) `@Override` on
  `handleMissingRequestHeader` broke against Spring 6.2.x's shifted
  signature — fixed by using a top-level `@ExceptionHandler` instead;
  (2) `@MockBean` import path typo (`.mock.mockito.`, not
  `.mockito.`); (3) **the day-2 bug** — the concurrent-insert race
  test failed with a confusing `AssertionFailure: null id` because
  Hibernate poisons the session the moment a constraint violation
  lands, so catching `DataIntegrityViolationException` in the same
  transaction and continuing (re-read the winning row) is a runtime
  error. Fixed by running the insert in `PROPAGATION_REQUIRES_NEW` via
  `TransactionTemplate`, so the failed insert's transaction rolls back
  in isolation and the outer flow re-reads on a healthy session.

Companion notes artifact for this week: **Saga Lab** at
`ticketing-platform/SAGA_LAB.html` — deep concepts + build log + bug
museum + file-by-file revision, same design system as `SEAT_LOCK.html`.

**Day 4 live-verified (2026-09-18).** Real docker-compose stack up
(postgres + redis + both services via `./mvnw spring-boot:run`).
Six failure experiments run against it, all outcomes match the paper
design in `WEEK2_DESIGN.md`. In the process, **three real bugs caught
live and fixed in-session** (documented in `SAGA_LAB.html` Bug Museum
§B4–B6): (4) Postgres init script silently skipped on a non-fresh
volume — manual DB create was the workaround, prod would need Flyway;
(5) `ignore-exceptions: [InventoryClientException]` matched the retry
subclass `InventoryTransientException` too (Resilience4j uses
`isInstance` matching) — ignore silently beat retry, so retry never
fired despite passing every unit test. Fix: drop `ignore-exceptions`
entirely, whitelist alone suffices. (6) CircuitBreaker fallback threw
`InventoryTransientException` — but Retry's outer aspect matched that
as retryable, so CB-open fast-fail was defeated by 3× wasted retry
rounds per request. Fix: fallback throws the non-transient base
`InventoryClientException`. Both fixes verified live: retry now fires 3×
in ~1500ms; CB opens after threshold and fast-fails in ~200ms
consistent; recovery via half-open probe worked when inventory came
back. All six experiments and all three bug-fix cycles in the
`SAGA_LAB.html` §"Day 4 · LIVE EVIDENCE" card with copy-pasted terminal
output.

## Week 1 Definition of Done

- [x] `hold` / `release` / `availability` endpoints working
- [x] Concurrent same-seat hold → one 200, one clean 409 (no crash, no oversell) — proven twice: automated (`ConcurrentHoldFailureExperimentTest`) and live (two real parallel curls, Day 5 above)
- [x] Redis TTL hold expires correctly (seat free) — `HoldReconciliationService`, Day 3
- [x] Global exception handling + correlation ID in logs — Day 3 / Day 4
- [x] Config env-driven, `.env.example` present, nothing hardcoded — `InventoryProperties`, Day 4
- [x] Docker Compose up → sab chalta hai ek command se — Day 4
- [x] 1+ integration test (Testcontainers) covering concurrent-hold — 2, Day 5
- [x] README with architecture note + run steps + the failure experiment
- [x] pushed to the repo (`GenAiBackend/ticketing-platform/inventory-service/`)
