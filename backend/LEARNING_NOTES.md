# Point #1 — Minimum Production Foundation: Learning Notes

This covers everything we've built so far on top of the UFC backend. Each
section has: what changed, the core concept, and self-check questions —
try answering those yourself before we discuss. Don't just read this
top-to-bottom; open the referenced files while you read.

---

## 1. Database schema consistency (Flyway)

**Files:** `pom.xml` (flyway-core, flyway-mysql), `src/main/resources/application.properties`,
`src/main/resources/db/migration/V1__baseline_schema.sql`

**What changed:** `spring.jpa.hibernate.ddl-auto` went from commented-out (undefined) to
`validate`. Flyway is now the schema owner, baselined at V1 to match the tables
that already existed in `ufcmain`.

**Core concept:** who "owns" the schema, and why letting Hibernate silently
create/alter tables is fine for a solo sandbox but breaks down the moment
more than one environment (your machine, a teammate's, CI, prod) needs the
same schema.

**Self-check:**
- If you add a new column to `Fighter` tomorrow, what exact file would you
  create, and what would you name it? (Look at the Flyway naming convention
  already used.)
- What would happen right now if you set `ddl-auto=update` again *and* kept
  Flyway active? Would they conflict?
- Why did we need `baseline-on-migrate` specifically for `ufcmain` but NOT
  for a brand-new empty database?

---

## 2. DTOs instead of exposing entities

**Files:** `src/main/java/com/ufc/backend/dto/WeightClassRequest.java`,
`WeightClassResponse.java`, `entities/WeightClass.java`

**What changed:** `POST /weight-classes` used to accept/return the raw
`WeightClass` entity. Now it goes through `WeightClassRequest` (in) and
`WeightClassResponse` (out).

**Core concept:** the entity is your *database* shape; the DTO is your *API
contract*. They will diverge the moment the domain grows, and only one of
them should be allowed to change freely.

**Self-check:**
- `WeightClass` has a `fighters` field (`@OneToMany`, lazy). What error would
  you have hit if we'd kept returning the entity from `GET /weight-classes/stream`
  once that list actually had data and Jackson tried to serialize it outside
  the transaction? Look up "LazyInitializationException" if the name doesn't
  ring a bell.
- I sent `{"weightClassId": 999, ...}` in a POST body during testing and the
  server ignored it. Why exactly — where in the code does that protection
  actually come from?

---

## 3. Bean Validation

**Files:** `WeightClassRequest.java`, `pom.xml` (spring-boot-starter-validation)

**What changed:** `@NotBlank`, `@NotNull`, `@Positive` on the request fields,
plus a custom `@AssertTrue`-annotated method (`isWeightRangeValid`) for a
cross-field rule (`maxWeight > minWeight`).

**Core concept:** Bean Validation constraints are declarative and fire before
your service code ever runs — but cross-field rules need a bit more than a
single annotation on a field.

**Self-check:**
- Why does `isWeightRangeValid()` check `if (minWeight == null || maxWeight == null) return true`
  instead of just comparing them directly? What would happen on a request
  with a null `minWeight` if that guard weren't there?
- If we later add a `Fighter` entity's `heightCm`/`reachCm`, what would a
  *realistic* validation rule look like for those fields? Is there a
  cross-field or cross-entity constraint that plain Bean Validation
  can't express?

---

## 4. Global exception handling / consistent errors

**Files:** `exception/GlobalExceptionHandler.java`, `exception/ResourceNotFoundException.java`,
`exception/ConflictException.java`, `optimistic/locking/ProductController.java`,
`optimistic/locking/ProductService.java`

**What changed:** `ProductController` used to have a try/catch per endpoint.
Now every exception is mapped once, centrally, to a `ProblemDetail` (RFC 7807).

**Core concept:** why scattering `try/catch` across controllers doesn't scale,
and why exception *type* (not string message) should drive the HTTP status.

**Self-check:**
- Why did we create `ResourceNotFoundException`/`ConflictException` instead
  of reusing Java's built-in `IllegalArgumentException`/`IllegalStateException`?
  What could go wrong if some unrelated piece of code throws
  `IllegalArgumentException` for a totally different reason?
- The generic `@ExceptionHandler(Exception.class)` handler returns a vague
  "An unexpected error occurred" message but logs the full exception. Why is
  hiding the real message from the client *and* logging it in full both
  necessary — what goes wrong if we only did one of the two?

---

## 5. Logging

**Files:** `BackendApplication.java`, `ProductSeedConfig.java`

**What changed:** `System.out.println` → SLF4J `Logger` (`log.info(...)`).

**Core concept:** a print statement can't be filtered, redirected, leveled,
or turned off per environment. A logger can.

**Self-check:**
- In `GlobalExceptionHandler`, some handlers use `log.warn` and one uses
  `log.error`. Why the difference? What's the practical impact if you searched
  production logs by level during an incident?

---

## 6. Secrets / config handling

**Files:** `application.properties`

**What changed:** `spring.datasource.username=${DB_USERNAME:root}`,
`password=${DB_PASSWORD:rajat}` — env-var driven, with a local fallback.

**Core concept:** the fallback exists *only* so your machine keeps working
without extra setup. It should not exist in a real deployment.

**Self-check:**
- The datasource URL is still hardcoded (`jdbc:mysql://localhost:3306/ufcmain...`).
  Is that a secret? Should it also be externalized — and if so, why is the
  reason different from why the password needed it?
- If someone deploys this app and forgets to set `DB_PASSWORD`, what happens
  right now? Is that good or bad?

---

## 7. Constructor injection consistency

**Files:** `WeightClassController.java`, `WeightClassService.java`,
`ProductController.java`, `ProductService.java`

**What changed:** every class now uses Lombok `@RequiredArgsConstructor`
instead of a mix of manual constructors, `@Autowired`, and commented-out
dead code.

**Core concept:** with exactly one constructor, Spring auto-wires it —
`@Autowired` on it is redundant. Field injection (`@Autowired private X x;`)
is the pattern we're avoiding entirely.

**Self-check:**
- Open `WeightClassServiceTest.java`. How is `WeightClassService` instantiated
  there — and would that even be possible if the service used field injection
  instead of a constructor?

---

## 8. API documentation (springdoc/Swagger)

**Files:** `pom.xml`

**What changed:** added `springdoc-openapi-starter-webmvc-ui`. Visit
`/swagger-ui/index.html` or `/v3/api-docs` once the app is running.

**The real bug we hit:** version `2.6.0` threw
`NoSuchMethodError: ControllerAdviceBean.<init>` at runtime — it was built
against an older Spring Framework than the one Spring Boot 3.4.3 ships
(6.2.3). Bumping to `2.8.3` fixed it.

**Self-check:**
- This error only showed up at *runtime*, not at compile time. Why didn't
  the compiler catch a mismatched method signature between two libraries?
- If Maven had refused to even download `2.8.3` (say, network blocked),
  what's a completely different way you could have worked around a
  springdoc/Spring Boot version mismatch?

---

## 9. Testing conventions + separation of responsibilities

**Files:** `BackendApplication.java`, `optimistic/locking/ProductSeedConfig.java`,
`src/test/java/com/ufc/backend/service/WeightClassServiceTest.java`,
`src/test/java/com/ufc/backend/controller/WeightClassControllerTest.java`

**The real bug we hit:** `WeightClassControllerTest` (`@WebMvcTest`) failed
to load its context entirely, because `BackendApplication` had a
`CommandLineRunner` bean depending on `ProductRepository` — and `@WebMvcTest`
doesn't filter out `@Bean` methods declared directly on the
`@SpringBootApplication` class the way it filters `@Component`-scanned beans.
Fix: moved that bean into its own `@Configuration` class
(`ProductSeedConfig`).

**Core concept:** three different "sizes" of test now exist in this project —
know which is which:
- `WeightClassServiceTest` — **unit test**: no Spring context at all, pure
  Mockito, tests one class's logic in isolation.
- `WeightClassControllerTest` — **slice test** (`@WebMvcTest`): loads only
  the web layer (controllers, `@ControllerAdvice`, Jackson, validation), the
  service is mocked, no database.
- `BackendApplicationTests` — **full integration test** (`@SpringBootTest`):
  loads everything, including a real connection to `ufcmain` and Flyway.

**Self-check:**
- Why couldn't a plain unit test (like `WeightClassServiceTest`) have caught
  the `@WebMvcTest` context-loading bug? What class of bug can *only* a
  slice or integration test catch?
- We deliberately did NOT add `@DataJpaTest` or Testcontainers this round.
  Given what actually changed (no new custom `@Query`), was that the right
  call? What would change your answer?

---

## What we deliberately did NOT change (and why)

- **Package structure** (`controller/service/repository/dto` at the top
  level, `optimistic.locking` and `practice` sitting separately) — layer-based
  organization is fine at this scale (one real feature). Revisit this when
  Fighter/Fight/Bet get real controllers — that's when feature-based
  packaging might start paying for itself.
- **`ProductSeedConfig` still seeds a new `Product` row on every app
  startup.** That's pre-existing behavior from before this round of changes,
  left alone because it's a dead/demo-code cleanup problem, not a foundation
  problem — flagging it here so it doesn't get forgotten.
- **`practice/Solution.java`** — unrelated LeetCode practice code sitting in
  `src/main`. Untouched, same reason.

---

# Round 2 — Concurrent Betting (optimistic locking on a real domain entity)

All 15 original "Point #1" items were done in Round 1. This round takes the
optimistic-locking mechanics already explored in the `Product` sandbox and
applies them to the real UFC domain for the first time: `Bet`.

**Files:** `entities/Bet.java`, `src/main/resources/db/migration/V2__add_bet_version.sql`,
`repository/{User,Fighter,Event,Fight,Bet}Repository.java`, `seed/ReferenceDataSeeder.java`,
`dto/{BetRequest,BetAmountUpdateRequest,BetResponse}.java`, `service/BetService.java`,
`controller/BetController.java`, `exception/InvalidRequestException.java`,
`src/test/java/.../BetServiceTest.java`, `BetControllerTest.java`, `BetConcurrencyTest.java`

## The scenario

Two users load the same bet (same `@Version` value), both edit the amount,
both hit save. Without a version check, the second save silently overwrites
the first — a **lost update**. `Bet` now has a `@Version` column (added via
`V2__add_bet_version.sql`, since it didn't exist before), so the second save
fails instead of silently winning.

## What's new besides Bet itself

- `Fighter`, `Event`, `Fight`, `User` had entities but **zero** repositories —
  added the plain `JpaRepository` interfaces for all four, since placing a
  bet needs to look them up.
- `ReferenceDataSeeder` — seeds one event/fight/two fighters/two users, but
  **only if the fight table is empty** (`fightRepository.count() > 0` guard).
  Contrast this with `ProductSeedConfig`, which has no such guard and creates
  a new row on *every* startup — that inconsistency is intentional to notice.
- `InvalidRequestException` (→ `400`) — a genuine domain rule: the fighter
  you're betting on has to actually be one of the two fighters in that fight.
  Not every bad input is a 404 or a 409.
- `BetRequest` has no `odds` field at all — the server assigns a fixed
  placeholder (`1.91`). Letting the client set its own odds would let it
  guarantee its own payout.

## Two different ways we proved the lock actually works

1. **`BetConcurrencyTest.sequentialStaleReads_...`** — fetches the same bet
   twice (two separate reads, so two separate copies both holding the same
   version), saves the first copy (succeeds), then tries to save the second
   (fails with `ObjectOptimisticLockingFailureException`). No real threads
   needed — this is deterministic every single run.
2. **`BetConcurrencyTest.trueConcurrentUpdates_...`** — two real threads
   (`ExecutorService`) both call `betService.updateBetAmount` on the same bet
   at once. Exactly one must succeed; the other must hit the same exception
   type. This one is closer to what actually happens under real traffic, but
   is less deterministic to reason about than test #1.
3. We also did it once live over real HTTP — two backgrounded `curl` PATCH
   requests at the same `/bets/{id}/amount` — got one `200` and one `409`
   ("This resource was modified by another request. Please retry.").

**Self-check:**
- Why does test #1 (sequential reads, no threads at all) prove the *exact
  same thing* as test #2 (real thread-level race)? What does optimistic
  locking actually check at commit time — does it care *how* your copy
  became stale?
- `BetController` has no `GET /bets/{id}` endpoint. I only proved the 409 by
  reading the PATCH response bodies directly. If you needed to verify the
  final state independently, what would you add, and where?
- Right now, `updateBetAmount` doesn't retry on conflict — it just surfaces
  the `409` to the client. Is "let the client retry" always the right answer
  here, or can you think of a case where the *server* should retry
  automatically instead?
- We used **optimistic** locking, not pessimistic (`SELECT ... FOR UPDATE`).
  Betting has way more reads than write-conflicts (most bets are never
  touched again after being placed). Given that, why is optimistic locking
  the right default here — and what kind of workload would flip that answer?

## What's still open (not done this round, on purpose)

- No `GET /bets` or `GET /bets/{id}` — only place + update-amount exist.
- No check that a fight is still open for betting (e.g. `Event`/`Fight`
  status) — right now you could bet on a fight that's already `COMPLETED`.
- No retry-with-backoff on the `409` path anywhere (client or server).
- `BetService` doesn't yet touch `Bet.status` (WON/LOST) — that's tied to
  fight results, which don't have an API yet either.

---

Try the self-check questions above first (both the Round 1 list and this
one). Come back with your answers or where you got stuck, and we'll go from
there.
