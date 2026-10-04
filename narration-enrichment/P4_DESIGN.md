# P4 Design — Async doc-processing pipeline (API + Worker split)

> **Day-1 deliverable for P4** (before any code). Same shape as
> `P2_DESIGN.md` / `P3_DESIGN.md`. What gets built + *why the shape
> is what it is* + 6 interview questions answered separately.
>
> **P4 goal (from `Jarvis_GenAI_Path.md`):** event-driven ingestion,
> idempotency, retries, backpressure. **First genuine microservice
> split on this track** — an API service that queues and returns,
> and a Worker service that does the embedding/LLM-heavy work. AWS:
> SQS + DLQ (+ the S3 backing P2 already wired). **"P4 = AWS ka asli
> ghar"** per the master plan — but per standing rule 3-2, every real
> AWS resource (queue, DLQ, bucket) is Rajat's to create; this
> codebase wires boto3 and proves everything against moto.

---

## Table of contents

1. [Why async, and why now](#1-why-async-and-why-now)
2. [The split — what becomes two services](#2-the-split)
3. [Data model — ingest_jobs](#3-data-model)
4. [The queue abstraction — in-memory first, SQS behind the same door](#4-the-queue-abstraction)
5. [The dual-write problem — ticketing's outbox lesson, applied](#5-the-dual-write-problem)
6. [Idempotency — at-least-once delivery made safe](#6-idempotency)
7. [Retries, DLQ, and the DEAD state](#7-retries-dlq-dead)
8. [Backpressure](#8-backpressure)
9. [Failure matrix](#9-failure-matrix)
10. [Sequence diagrams](#10-sequence-diagrams)
11. [Endpoint contracts](#11-endpoint-contracts)
12. [The [Claude]/[Rajat] boundary](#12-the-clauderajat-boundary)
13. [Interview questions](#13-interview-questions)

---

## 1. Why async, and why now

`POST /policies/ingest` today is synchronous: checksum → chunk →
**one embedding call per chunk** → atomic store, all inside the HTTP
request. That was the right smallest-thing for P2. It stops being
right the moment docs get real, for reasons this project has already
*measured*, not guessed:

- **The embedding quota is tiny and known** (P1 Week 2 found the
  free-tier caps live; the Week 4 rate limiter encodes 5/min). A
  40-chunk document = 40 embed calls = **8 minutes of wall-clock at
  5/min**. No HTTP client waits 8 minutes; the request dies at the
  timeout and the work is lost mid-way.
- **Failure mid-ingest wastes everything.** Today a 503 on chunk 39
  of 40 aborts the whole ingest (deliberately — partial-embed state
  is worse than none). Synchronously, the caller just… retries the
  whole thing, re-spending the 38 successful calls' worth of quota
  on a paid tier, or burning the day's quota on free.
- **Ingest load is spiky, enrich load is steady.** One admin
  uploading 10 policy docs should not freeze `/enrich` for every
  user while the API process grinds embeddings.

The fix is the oldest shape in distributed systems: **accept fast,
work later.** `POST /policies/ingest-async` validates, records a
job, enqueues, returns **202 + job_id** in milliseconds. A separate
Worker process drains the queue at whatever pace the quota allows.

**Non-goal:** the existing synchronous `/policies/ingest` stays. It
is the right tool for small docs, tests, and seeding — and keeping
it proves the split is *additive*, not a rewrite.

---

## 2. The split

```
           ┌────────────────────┐          ┌─────────────────────┐
  HTTP ──► │  API service        │          │  Worker service      │
           │  (FastAPI, main.py) │          │  (worker.py loop)    │
           │  · validate         │          │  · receive message   │
           │  · write job row    │  queue   │  · claim job row     │
           │  · enqueue          │ ───────► │  · chunk+embed+store │
           │  · 202 {job_id}     │          │  · mark DONE/FAILED  │
           └─────────┬───────────┘          └──────────┬──────────┘
                     │                                 │
                     └───────────► SQLite ◄────────────┘
                          (shared DB = source of truth)
```

Same codebase, same package, **two entry points**: `uvicorn
narration_enrichment.main:app` (API) and `python -m
narration_enrichment.worker` (Worker). This is the honest version of
"microservice split" at this scale — separate *processes* with a
queue between them, not separate repos/containers (containers arrive
when this deploys to ECS; the process boundary is what changes the
design, and it changes it now).

**Why the worker is NOT a FastAPI background task:** BackgroundTasks
die with the process, share the API's event loop and its CPU, and
give no delivery guarantee — a deploy mid-task loses the job
silently. The whole point of P4 is that the work *survives* the API
process. That requires the job to live in durable state (DB row +
queue message), not in process memory.

---

## 3. Data model

One new table:

```python
class IngestJob(Base):
    __tablename__ = "ingest_jobs"
    id            : str  PK        # UUIDv4 — exposed in GET /jobs/{id}
    doc_id        : str            # target policy doc
    title         : str
    content       : str            # the raw text to ingest (small docs;
                                   #   S3-pointer variant is a P4 stretch)
    checksum      : str            # sha256(content), computed at enqueue
    source_uri    : str | None     # S3 URI when the raw doc was backed
    status        : str            # QUEUED → PROCESSING → DONE
                                   #        ↘ FAILED (retryable) ↘ DEAD
    attempts      : int            # incremented on each claim
    error         : str | None     # last failure, human-readable
    created_at    : datetime
    started_at    : datetime | None
    finished_at   : datetime | None
```

**The job row is the source of truth; the queue message is a
delivery hint.** The message carries only `job_id`. Everything the
worker needs lives in the row. This is what makes re-delivery,
recovery sweeps, and "what happened to my upload?" all trivially
answerable from one place — and it is the same decision ticketing's
outbox made (`OutboxEvent` row = truth, HTTP push = hint).

**Status lifecycle (one-way, like payment's state machine):**

```
QUEUED ──claim──► PROCESSING ──ok──► DONE            (terminal)
                      │
                      └──error──► FAILED ──re-enqueue──► QUEUED
                                     │
                                     └── attempts ≥ max ──► DEAD   (terminal)
```

---

## 4. The queue abstraction

```python
class JobQueue(Protocol):
    def send(self, job_id: str) -> None: ...
    def receive(self, max_messages: int = 1) -> list[QueueMessage]: ...
    def delete(self, message: QueueMessage) -> None: ...   # ack
    def depth(self) -> int: ...                            # approx, for ops
```

Two implementations behind it:

- **`InMemoryJobQueue`** — a `deque` with visibility-timeout
  semantics faked well enough for tests and single-machine dev.
  Default when `INGEST_QUEUE_URL` is empty — exactly the
  `policy_s3_bucket: ""` pattern from P2 Day 4: the AWS code path
  exists, is off by default, and dev needs zero AWS.
- **`SqsJobQueue`** — boto3 against a real/moto SQS queue.
  `receive` maps to `ReceiveMessage` (long-poll), `delete` to
  `DeleteMessage`, visibility timeout and `maxReceiveCount`/DLQ are
  queue-level config that **Rajat's Terraform** sets (§12).

**Why an abstraction at all, given rule 3-7 (don't overengineer):**
because there are genuinely two implementations from day one — tests
+ dev need in-memory, the deploy target is SQS — and the interface
is four methods. This is the "second concrete case justifies the
interface" rule from NEXT_PATH's own Strategy-pattern note, not
speculative abstraction.

---

## 5. The dual-write problem

Enqueue-and-insert is two writes to two systems — the exact
dual-write ticketing Week 3 defeated with the outbox. If the API
does `INSERT job` then `queue.send()` and crashes between them, the
job is QUEUED in the DB but no message exists: **a dangling job**
that no worker will ever pick up.

Full outbox (poller publishing from an outbox table) is more
machinery than this needs, because here **the job table can be its
own outbox.** The P4 shape:

1. `INSERT ingest_jobs (status=QUEUED)` — **commit**.
2. `queue.send(job_id)` — best-effort, after commit.
3. A **recovery sweep** in the worker (same decision-tree shape as
   `BookingRecoveryService`): any job still QUEUED older than
   `stale_after` seconds gets re-enqueued. Any job PROCESSING older
   than a (longer) threshold had its worker die mid-flight → mark
   FAILED, let the retry path decide.

Crash between 1 and 2 → the sweep re-sends. Send succeeds but the
message is duplicated by the sweep → idempotency (§6) makes the
duplicate harmless. **At-least-once everywhere, exactly-once
nowhere** — the honest contract, same as the outbox lab proved.

---

## 6. Idempotency

Three layers, each cheap:

1. **Enqueue-time:** same `(doc_id, checksum)` already DONE → the
   API returns the existing job as `unchanged` without creating a
   new one — P2's checksum fast-path lifted to the job layer. Same
   pair already QUEUED/PROCESSING → return *that* job_id (don't
   double-queue identical work).
2. **Claim-time:** the worker claims by compare-and-set
   (`UPDATE ... SET status=PROCESSING WHERE id=? AND status IN
   (QUEUED, FAILED)`). A message re-delivered while the job is
   already PROCESSING/DONE matches zero rows → ack and drop. This is
   the consumer-dedup lesson from ticketing Day 7, with the status
   column playing the role of the `processed_event` table.
3. **Effect-time:** the actual work ends in
   `upsert_policy_doc_with_chunks` — already a replace-by-doc_id
   atomic upsert (P2 Day 3). Running it twice converges to the same
   terminal state.

---

## 7. Retries, DLQ, DEAD

**Worker-side retry is for the *job*; tenacity's retry is for the
*call*.** The existing 429/503/504 whitelist retry stays wrapped
around each embed call. If the call-level retry exhausts, the job
attempt fails: status → FAILED, `error` recorded, attempts counted.

- `attempts < max_attempts` (default 3): FAILED jobs are re-enqueued
  by the sweep with the attempt counter intact.
- `attempts ≥ max_attempts`: status → **DEAD**. Terminal. A human
  looks at `error` and decides.

**SQS's own DLQ** (maxReceiveCount on the real queue) is the
belt-and-braces for messages the worker *crashes on* before it can
even mark FAILED — poison messages. The DB's DEAD state and SQS's
DLQ answer two different failures: "the work keeps failing" vs "the
message keeps killing the consumer." Both exist; `GET /ops/ingest`
surfaces both.

**No retry on non-transient failures:** a `ValueError` (empty
content, zero chunks) marks the job DEAD immediately — retrying a
deterministic failure is quota arson. Whitelist thinking again
(ticketing Bug 5 / narration's 429-503-504 rule): *retryable is an
explicit list, never a default.*

---

## 8. Backpressure

The queue IS the backpressure mechanism — that's why it exists. The
API never slows down because the worker is busy; the queue absorbs
the spike. What P4 adds on top:

- **Visibility:** `GET /ops/ingest` returns queue depth, per-status
  job counts, DLQ count (0/None when in-memory), oldest-QUEUED age.
  Persisted-observability invariant (P3 #4): the jobs table already
  *is* the persistence; the endpoint is one aggregate query — same
  shape as `/stats`.
- **A bounded intake valve:** if QUEUED + PROCESSING exceeds
  `ingest_max_backlog` (config, default generous), the API returns
  **429 + Retry-After** instead of enqueueing. An unbounded queue in
  front of a 5/min worker is a promise the system can't keep; better
  to refuse honestly at intake than to accept work that won't run
  for hours. Reuses the 429 + Retry-After contract the rate limiter
  already established.
- **The worker paces itself** with the existing `RateLimiter`
  against the embed quota — backpressure at the source of scarcity,
  not a guess.

---

## 9. Failure matrix

| Failure | Behavior | Rule enforced |
|---|---|---|
| API crashes after job INSERT, before send | Sweep re-enqueues stale QUEUED job | Job row = truth, message = hint (§5) |
| Message delivered twice | Claim CAS matches 0 rows on 2nd delivery → ack+drop | Idempotent consumer (§6) |
| Worker dies mid-PROCESSING | Sweep marks stale PROCESSING → FAILED → retry path | Dangling-saga recovery, Python edition |
| Embed 503s exhaust call-level retry | Job FAILED, attempts++, re-enqueued up to max | Call-retry ≠ job-retry (§7) |
| Empty/invalid content reaches worker | DEAD immediately, no retry | Deterministic failure ≠ transient (§7) |
| attempts ≥ max | DEAD + error kept | Human decision point, not silent loop |
| Poison message crashes worker pre-claim | SQS redrive → DLQ after maxReceiveCount | Queue-level belt-and-braces (§7) |
| Backlog over `ingest_max_backlog` | 429 + Retry-After at intake | Honest refusal over unbounded promise (§8) |
| Queue unreachable on send | Job stays QUEUED; 202 still returned; sweep retries send | Degrade-not-fail: intake survives queue outage |
| GET /jobs/{id} for other key's job / missing | Same 404 body | Existence-hiding invariant (P3 #2) |

---

## 10. Sequence diagrams

### 10a. `POST /policies/ingest-async` — happy path

```
Client ──► POST /policies/ingest-async   X-API-Key: <raw>
             { doc_id, title, content }
             │
             ▼
        [require_api_key]                      (P3 invariant #1)
             │
             ▼
        checksum = sha256(content)
             │
             ├─ (doc_id, checksum) already DONE?    → 200 unchanged
             ├─ already QUEUED/PROCESSING?          → 202 same job_id
             ├─ backlog > ingest_max_backlog?       → 429 + Retry-After
             │
             ▼
        BEGIN TX: INSERT ingest_jobs(QUEUED)  COMMIT
             │
             ▼
        queue.send(job_id)        ← best-effort, post-commit
             │
             ▼
        202 { job_id, status: "QUEUED" }
```

### 10b. Worker loop — one message

```
receive() ──► msg(job_id)
                │
                ▼
        CAS claim: QUEUED|FAILED → PROCESSING, attempts++
                │
                ├─ 0 rows matched → delete(msg), drop   (duplicate)
                ▼
        chunk → embed each (RateLimiter + tenacity whitelist) → upsert
                │
                ├─ ok    → status=DONE,   delete(msg)
                ├─ transient exhausted
                │        → status=FAILED (sweep re-enqueues if attempts<max)
                │          delete(msg)
                └─ deterministic error
                         → status=DEAD,   delete(msg)
```

### 10c. Recovery sweep (worker, every N seconds)

```
stale QUEUED     (age > stale_after)      → queue.send(job_id) again
stale PROCESSING (age > processing_max)   → status=FAILED
FAILED  attempts<max                      → queue.send(job_id)
FAILED  attempts≥max                      → status=DEAD
```

---

## 11. Endpoint contracts

### `POST /policies/ingest-async`  *(auth-gated)*

Request = same body as sync ingest. Responses: **202**
`{job_id, doc_id, status}`; **200** `{job_id, status:"DONE",
unchanged:true}` on checksum fast-path; **429** over backlog; **401**
as standard.

### `GET /jobs/{job_id}`  *(auth-gated)*

**200** `{job_id, doc_id, status, attempts, error, created_at,
started_at, finished_at}`; **404** missing (existence-hiding body).

### `GET /ops/ingest`  *(auth-gated)*

**200** `{queue_depth, dlq_depth, jobs: {QUEUED: n, PROCESSING: n,
DONE: n, FAILED: n, DEAD: n}, oldest_queued_age_seconds}` —
`dlq_depth: null` when the in-memory queue is active.

---

## 12. The [Claude]/[Rajat] boundary

| Step | Who |
|---|---|
| ingest_jobs table, queue abstraction, worker loop, sweep, endpoints, all tests (moto for SQS) | **[Claude]** |
| Terraform for SQS queue + DLQ + redrive policy (authored into `infra/` as code) | **[Claude]** authors, **[Rajat]** reviews |
| Creating the real queue/DLQ (terraform apply), real AWS credentials, `INGEST_QUEUE_URL` in `.env` | **[Rajat]** (rule 3-2) |
| Live end-to-end against real SQS | **[Rajat]**-driven session, Claude pairs |

Until Rajat flips `INGEST_QUEUE_URL`, everything runs on the
in-memory queue — the whole pipeline is buildable, testable, and
demonstrable without a single AWS resource existing.

---

## 13. Interview questions

1. **"Why not FastAPI BackgroundTasks?"** — the three guarantees a
   queue+job-row gives that in-process background work can't. Then
   the reverse: name one workload where BackgroundTasks is the
   *right* call and SQS is overkill.

2. **The message carries only `job_id`, not the content. Defend
   that** against "put the payload in the message and skip the DB
   read." What breaks at SQS's 256KB message cap, and what breaks
   for the recovery sweep, under the payload-in-message design?

3. **Walk the crash windows:** API dies (a) before INSERT, (b) after
   INSERT before send, (c) after send. Worker dies (d) after claim
   before upsert, (e) after upsert before DONE. For each: what state
   is left, and which mechanism repairs it?

4. **Exactly-once vs at-least-once:** this design chose at-least-once
   + idempotent effects. What would exactly-once actually require
   here, and why is "idempotent at-least-once" the standard answer?
   Where in THIS codebase is the idempotency enforced (name the
   function/query)?

5. **DB DEAD state vs SQS DLQ — why both?** Give one failure that
   only lands in DEAD, one that only lands in the DLQ, and what an
   operator does differently with each.

6. **The intake 429 (backlog cap) vs the rate-limiter 429 (quota
   cap) — same status code, different resource being protected.**
   What is each one actually telling the caller to do, and why is
   returning 202-and-queue-it-anyway the wrong answer once the
   backlog cap is hit?

---

*Design paper, not a plan. The plan lives in `ROADMAP.md` §3C.
Update this file only if a design decision genuinely changes during
implementation — a change that would affect an interview answer.*
