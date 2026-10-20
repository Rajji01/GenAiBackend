# Prod Hardening — Netflix-class failure modes, applied to this system

> **Day-1 deliverable for the Hardening arc (P5.5)** — the plan Rajat
> asked for ("bade projects jaise Netflix ka microservices architecture
> jaisa... realistic tough prod problems"). Same paper-first discipline
> as P2–P5.
>
> **What this is:** the catalog of REAL production failure classes that
> big-fleet systems (Netflix, Stripe, AWS post-mortems) are built
> around, each mapped honestly to THIS codebase: already solved (and
> where), built in this arc, or out of scope at this scale (named, not
> hidden — rule 3-7). The point is not cosplay of Netflix's stack; it
> is that every one of these failure classes exists at ANY scale the
> moment you depend on a flaky expensive upstream — which is exactly
> what an LLM provider is.

---

## 1. The catalog — the problems, in post-mortem language

| # | Failure class | The war story shape | This repo today | This arc |
|---|---|---|---|---|
| 1 | **Retry storm** | an outage gets WORSE because every client retries into it; recovery is impossible under self-inflicted load | ✅ partly: whitelisted retries only (429/503/504), bounded attempts | **Circuit breaker** (H2) — stop calling a provider that is DOWN, not just slow |
| 2 | **Sustained dependency outage** | the 20s timeout × every request = threadpool exhaustion; the whole API goes down because ONE upstream did | ❌ today every /enrich waits the full timeout during an outage | **Circuit breaker** (H2): fail fast in µs while OPEN, probe on cooldown |
| 3 | **Duplicate spend on client retries** | client times out, retries, the charge/LLM call happens TWICE; at Stripe this is double-billing, here it is double quota | ❌ /enrich is not idempotent across client retries | **Idempotency keys** (H3), Stripe-style |
| 4 | **Overload collapse / no load shedding** | the system accepts more work than it can finish; latency climbs until EVERYTHING times out (metastable failure) | ✅ partly: P4's 429 intake valve (queue backlog), rate limiter (quota) | **Concurrency shed** (H4): cap in-flight enrich work, fast-503 the overflow |
| 5 | **Cache stampede / thundering herd** | a hot key expires, 10k requests recompute it simultaneously | ◻️ out of scope AT THIS SCALE (single process, no cache tier) — named here so nobody pretends it's solved | — (noted in H4's design as the next step after a cache exists) |
| 6 | **Poison pill** | one malformed message crashes every consumer that touches it, forever | ✅ P4: DEAD state + SQS DLQ (two nets, two failure kinds) | covered — chaos suite re-proves it (H5) |
| 7 | **Dual write / lost event** | DB committed, message never sent (or vice versa) | ✅ P4: job-row-is-truth + recovery sweep; ticketing outbox | covered — chaos suite re-proves it (H5) |
| 8 | **Zombie consumer / duplicate delivery** | at-least-once delivery meets a non-idempotent consumer | ✅ P4: CAS claim + idempotent upsert | covered (H5) |
| 9 | **Gray failure** | the dependency is not DOWN, it is SLOW — health checks pass, users suffer | ✅ partly: hard client timeout (20s, measured not guessed) | breaker counts timeouts as failures (H2) — slow-is-down after a threshold |
| 10 | **Blast radius of a compromised component** | one bad actor/component can touch everything | ✅ P5: read-only whitelisted tools, bounded loop, full audit | covered |

The honest pattern in that table: **the queue/consumer class is already
built** (P4/P5 did the Netflix homework for async); what is missing is
the **synchronous request path's survival kit** — items 1–4. That is
this arc.

---

## 2. H2 — Circuit breaker on the provider boundary

**The problem, concretely here:** during a sustained Gemini outage,
every `/enrich` and `/chat` call burns a 20-second timeout, holds a
threadpool worker the whole time, runs tenacity's bounded retries
INTO the dead provider, and returns 503 anyway. 50 requests/min of
traffic = 50 held threads and zero successes. tenacity answers "this
CALL failed, try again"; nothing answers "this PROVIDER is down, stop
asking."

**The design (Hystrix's state machine, smallest honest version):**

```
CLOSED ──(N consecutive whitelisted failures)──► OPEN
OPEN   ──(cooldown elapsed)──► HALF_OPEN (one probe allowed)
HALF_OPEN ── probe succeeds ──► CLOSED (counters reset)
HALF_OPEN ── probe fails    ──► OPEN   (fresh cooldown)
```

- **Pure Python, no new dependency** (rule 3-7 — resilience4j-envy is
  not a requirement). One class, `threading.Lock`, injectable
  `time_fn` (the rate-limiter/queue-fake pattern).
- **Trips only on the whitelist** — the same 429/503/504 + timeout
  list every retry decision in this repo uses. A 422 (bad input) or a
  Pydantic validation failure is the CALLER'S problem and must never
  open the breaker: tripping on non-transients turns one weird request
  into a self-inflicted outage.
- **Consecutive-failure threshold (5), not a rolling error-rate
  window.** Error-rate windows are the right call at Netflix's RPS;
  at this traffic a rate window is noise-sensitive and
  overengineered. Flagged as the first thing to revisit at real load.
- **OPEN → instant `CircuitOpenError(retry_after)`** → route maps to
  503 + Retry-After in microseconds. No thread held, no quota spent,
  no retry storm.
- **HALF_OPEN admits exactly ONE probe** (others fail fast): the
  recovery test costs one request, not a herd.
- **Scope: one breaker per process around the generative-LLM
  boundary** (enrich + chat share it — same upstream, shared fate is
  honest). Embedding calls already degrade-not-fail and do not hold
  the request hostage; wiring them is a later decision, noted in H5.

**Failure experiment (test-level):** drive 5 whitelisted failures →
assert 6th call never reaches the (exploding) client; advance the
fake clock past cooldown → exactly one probe allowed; probe success
closes, probe failure re-opens with a fresh cooldown.

---

## 3. H3 — Idempotency keys on /enrich

**The problem, concretely here:** a client sends `/enrich`, the LLM
takes 19s, the client's own 10s timeout fires, the client retries —
the narration gets enriched TWICE: twice the quota, two DB rows for
one real transaction. At Stripe this exact shape is double-charging a
card; the defense is the same.

**The design (Stripe's contract, smallest honest version):**

- Optional header `Idempotency-Key: <client-chosen string>`. Absent →
  exactly today's behavior.
- New table `idempotency_keys(key PK, request_hash, response_json,
  created_at)`.
  - **Replay:** key seen + same `sha256(body)` → return the STORED
    response, marked `X-Idempotent-Replay: true`, zero LLM calls.
  - **Misuse:** key seen + DIFFERENT body hash → 422. A key names one
    logical operation; reusing it for different bytes is a client bug
    that must fail loudly, not silently return someone else's answer.
  - **Miss:** process normally, store (key, hash, response) in the
    same transaction-ish step; a unique-constraint race (two
    concurrent retries) resolves by re-reading the winner's row — the
    ticketing Day-7 dedup shape.
- **Only successful (200) responses are stored.** A 503 is not an
  outcome worth replaying — the client SHOULD retry that and get a
  fresh attempt.
- **No TTL in this arc** (rule 3-7): the table is tiny at this scale
  and expiry policy is a product decision. Flagged, not built.

**Failure experiment:** same key + same body twice → one LLM call
total (mock call-count), identical response, replay header. Same key
+ different body → 422, no LLM call.

---

## 4. H4 — Load shedding on the sync path

**The problem, concretely here:** uvicorn's threadpool will happily
accept 100 concurrent `/enrich` requests even though the rate limiter
will reject 95 of them AFTER they've each done retrieval work, and a
provider slowdown multiplies held threads (metastable failure: the
system is busiest exactly when it can do the least). Netflix's answer
is concurrency-limited bulkheads: beyond N in-flight, reject in
microseconds — a fast no is kinder than a slow timeout.

**The design:** a module-level bounded in-flight counter (lock +
injectable everything, same testing pattern) wrapped around the
expensive section of `/enrich` (+ batch). Full → immediate 503
`Retry-After: 1` with a `shed` reason in the body. Deliberately NOT
asyncio semaphores or queue theory — count, compare, reject.

**Failure experiment:** saturate the counter manually, assert the
next call 503s in fast-path without touching retrieval/LLM mocks,
assert release restores service. Plus the composition question the
tests must answer: shed (503) fires BEFORE quota (429)? — order
documented and pinned.

---

## 5. H5 — Chaos suite: the invariants under combined failure

Single-fault behavior is tested per feature. Production failures
arrive in COMBINATIONS (the AWS post-mortem classic: the mitigation
for fault A amplified fault B). `tests/test_chaos.py` scripts the
combinations and asserts system-level invariants:

- Provider down + breaker OPEN + client retries with idempotency key
  → fast 503s, ZERO provider calls, no stored garbage to replay.
- Breaker OPEN while queue worker runs → async pipeline keeps its own
  retry/DEAD discipline (the worker's fate is not the API's fate).
- Embed down + provider up → enrich still 200s (P2 invariant), chat
  tools still work (P5's two-channels win), breaker does NOT trip
  (embedding is outside its boundary — pinned explicitly).
- Shed full + breaker OPEN → shed answers first (cheapest no wins).

This file is also where the catalog's "✅ covered" rows get RE-proven
in combination, so the table above stays a claims ledger with
evidence, not a brochure.

---

## 6. Day plan + DoD (mirrors ROADMAP §3F)

- **H1 (this paper)** — the catalog + designs + this DoD.
- **H2** — `circuit_breaker.py` + wiring into enrich/chat + tests.
- **H3** — idempotency keys on /enrich + tests.
- **H4** — load shedding + ordering-of-rejections pinned + tests.
- **H5** — chaos suite + README "Production hardening" section +
  LAB/STUDY/ROADMAP/AGENTS/FILE_GUIDE closeout.
- **Open after the arc (named, not hidden):** error-rate breaker
  window (needs real RPS), idempotency TTL (product call), cache tier
  + stampede defense (needs a cache to exist), live chaos drill
  against real Gemini (Rajat's quota, rule 3-6).

---

## 7. Interview questions (the arc's six)

1. Retry-with-backoff, rate limiter, circuit breaker, load shedder —
   four "stop calling" mechanisms in one codebase. For each: what
   SIGNAL does it read, what RESOURCE does it protect, and give the
   one failure only IT catches.
2. Why must the breaker trip only on the transient whitelist? Give
   the concrete self-inflicted-outage scenario if a 422 counted, and
   connect it to ticketing Bug 5.
3. Defend consecutive-failures over a rolling error-rate window at
   this system's traffic — then state the load level and the symptom
   that would force the switch.
4. The idempotency store keeps only 200s. A teammate wants to store
   503s too "so retries are cheap." Walk why that breaks the
   contract's purpose, and what the client's correct 503 behavior is.
5. Order the three rejections (shed 503, breaker 503, quota 429) for
   one incoming request and defend the order by cost-of-saying-no.
6. "Metastable failure" (the term of art): define it, show which TWO
   mechanisms in this arc specifically prevent the system entering
   that regime, and name the Netflix/AWS post-mortem shape it comes
   from.

---

*Companion to `P5_DESIGN.md` and friends; the live chaos drill
against real Gemini is Rajat's per rules 3-2/3-6. Plan lives in
`ROADMAP.md` §3F.*
