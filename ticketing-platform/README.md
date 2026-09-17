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
