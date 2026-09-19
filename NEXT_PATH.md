# Next Path — both tracks, week-by-week & day-by-day

Synthesized from `Jarvis_Architect_Path.md` (ticketing), `Jarvis_GenAI_Path.md`
(narration), `JARVIS_OPENAI_CONTEXT.md`, both `LEARNING_NOTES.md`, both HTML
companions (`SEAT_LOCK.html`, `NARRATION_LAB.html`), and the deep memory
files from past Claude sessions. Legend:

- **[PLAN]** = word-for-word from the master roadmap files
- **[PROPOSAL]** = my breakdown; only Week 1 of each track was fixed in the
  original briefs, everything else was collaborative — so past Week 1 the
  day plans are my proposal, to be refined before starting each week

Rule from `Jarvis_Architect_Path.md`: **"Week N+1 tab tak nahi jab tak N ka
DoD green na ho."** Same rule for both tracks.

---

## Where we are RIGHT NOW (2026-09-17 EOD)

### Ticketing — Week 1 (Phase 0)

- Days 1–5 done + Weekend `confirm` endpoint added.
- **41 tests green** (real Postgres + Redis via Testcontainers). afterCommit
  fix for the Redis-key-delete-before-commit race is in.
- **Not yet committed:** `confirm` endpoint, its tests, afterCommit fix,
  `SEAT_LOCK.html` still has no card for `confirm`.
- **BLOCKING Phase 1:** `WEEK1_REVIEW.md` interview Qs + LLD reflection —
  YOUR answers first, then evaluation.

### Narration — Week 4 done

- Week 4 features shipped: self-imposed rate limiter, correlation IDs
  (with the live logging-filter bug caught), `/stats` endpoint.
- **59 tests green**, 0 live calls in the suite.
- Last commit `20cb3c6`, all pushed. No pending direction chosen yet.

---

# TRACK A — TICKETING (Jarvis Architect Path)

## Phase 0 — Week 1 CLOSE-OUT (immediate)

Just to finish Week 1 cleanly before Phase 1 opens:

- **[PROPOSAL] Sunday** — you answer WEEK1_REVIEW.md (7 interview Qs +
  4 bonus B1–B4 + LLD reflection). I evaluate. Commit `confirm` + tests +
  afterCommit fix as one clean commit ("Week 1 close-out: /confirm +
  afterCommit fix + weekend review"). Update `SEAT_LOCK.html` with:
  a `confirm` flow diagram, an idempotency deep-dive comparing `hold`'s
  Redis-based check to `confirm`'s durable `booked_by_holder_id` check,
  and a bug-museum entry for the afterCommit race. Push after your OK.

## Phase 1 — First AWS footprint via LocalStack (~Week 2)

**[PLAN goal]** AWS: **S3** (ticket PDF / event images), AWS SDK v2
basics, presigned URLs. LLD: Repository, Strategy (pricing/discount).
HLD: service boundaries, DB-per-service, object vs block vs file storage.

**[PROPOSAL] Day plan:**

- **Day 1** — LocalStack in `docker-compose.yml` (S3 only). Create a
  `TicketStorageService` interface behind a Repository-style boundary
  (Strategy: local vs LocalStack S3 vs future real S3). One integration
  test using Testcontainers-LocalStack that uploads a byte[] and reads it
  back. HLD note: **why an object store, not a DB blob column** (write
  once, read many, cheap, presignable, no DB bloat).
- **Day 2** — Generate a real ticket PDF (openpdf or Apache PDFBox) on
  `confirm` success, upload to S3, store the S3 key on the seat row.
  Reason through: sync inside `confirm` (blocks the caller) vs async
  (Phase 3's real answer). For now sync, deliberately, with a note on
  what will move async and why.
- **Day 3** — `GET /shows/{showId}/seats/{seatId}/ticket` returns a
  short-lived **presigned URL** (5 min). Reason through: why presigned
  URL, not proxy-through the app. Rate-limit the endpoint at the
  controller level.
- **Day 4** — Strategy pattern for pricing/discount (regular vs
  member vs promo) applied to a stub `PriceCalculator` — even if pricing
  is trivial today, this is where Phase 2's discount rules will slot in
  cleanly. Anti-pattern reflection: don't build the abstraction until you
  have >1 concrete case, so Day 4 also adds the SECOND strategy (promo)
  to justify the interface.
- **Day 5** — LocalStack failure experiments: kill LocalStack mid-upload,
  what does the app do? Slow S3 (LocalStack has an artificial-latency
  knob), does the app degrade gracefully? Time-boxed to 1 day; the
  finding here shapes Phase 2's Resilience4j design.
- **Weekend** — LLD reflection: Repository + Strategy, real problem each
  one solved (not a checkbox). Update `SEAT_LOCK.html`. **Interview Qs
  answer-first:** DB blob vs object store, presigned URL vs proxy, when
  Strategy is over-engineering vs justified.

**[PLAN DoD hint]** LocalStack integration test present, S3 storage
abstracted behind a repository, presigned URL flow verifiable end-to-end.

## Phase 2 — Containerize + split into services (~Weeks 3–4)

**[PLAN goal]** Add `catalog-service` + `booking-service` +
`payment-service`. Sync comm (REST/OpenFeign) + Resilience4j
(retry/CB/timeout/bulkhead). All dockerized. LLD: Adapter (payment
gateways), Factory. HLD: sync vs async trade-off, API gateway intro,
service decomposition.

**[PROPOSAL] Weekly split:**

- **Week 3 Day 1–2** — `catalog-service` skeleton (Postgres, own
  container, own DB). Contract: shows, venues, seat-maps. inventory-service
  now HAS to call it to validate a `showId` really exists (Week 1 had a
  deliberate `// TODO` for this — that TODO becomes the trigger for
  splitting).
- **Week 3 Day 3–4** — OpenFeign client from inventory-service →
  catalog-service. Resilience4j: timeout + retry + circuit breaker.
  **Failure experiment:** kill catalog-service, watch inventory-service's
  circuit open, watch it half-open when catalog comes back. Do NOT skip
  this — it's the whole reason Resilience4j is being added, not the
  "installed the dependency" checkbox.
- **Week 3 Day 5** — `booking-service` skeleton. Orchestrates:
  catalog(read) → inventory(hold) → payment(charge, stub) → inventory
  (confirm). Idempotency key on the booking endpoint.
- **Week 4 Day 1–2** — `payment-service` with Adapter pattern for a stub
  UPI adapter + a stub Card adapter. Factory to pick the adapter based on
  the request. Payment success/timeout paths both exercised.
- **Week 4 Day 3–4** — Wire the full money flow: `booking-service`
  orchestrates end to end. Payment timeout → **compensate** = release
  hold. Verify: a timed-out payment leaves the seat AVAILABLE after
  compensation (this is Phase 3's first taste of saga semantics, done
  synchronously for now).
- **Week 4 Day 5** — API gateway (Spring Cloud Gateway) as the single
  entry point. Route by path prefix. HLD note: **when a gateway earns
  its cost** (auth, rate-limit, routing centralization) vs premature.
- **Weekend** — Big LLD reflection: what got repeated across services
  (correlation-ID filter, exception handler shape) — the DRY temptation
  vs the DRY-across-services trap (shared libs = deployment coupling).

## Phase 3 — Messaging, REAL AWS begins (~Weeks 5–6)

**[PLAN goal]** Booking confirmed → **SNS** fan-out → **SQS** →
`notification-service` + `analytics-service`. DLQ, visibility timeout,
idempotent consumer, duplicate handling. LLD: Observer/event-driven,
idempotent consumer. HLD: event-driven, eventual consistency, **Outbox
pattern**. **[PLAN Failure]:** kill notification consumer → watch queue
depth → messages land in DLQ.

**[PROPOSAL] Weekly split:**

- **Week 5** — real AWS SNS + SQS (LocalStack ≠ real for messaging).
  Publish `BookingConfirmed` from booking-service. Two subscribers:
  `notification-service`, `analytics-service`. Idempotent consumer via
  the outbox pattern or a dedup table. **Verify DLQ live:** deliberately
  break the notification consumer, watch messages accumulate, then land
  in DLQ after visibility timeout × maxReceiveCount.
- **Week 6** — Outbox pattern properly: booking-service writes the
  domain change + the outbox row in the SAME Postgres transaction, a
  separate poller publishes to SNS. Prove it: kill the process between
  DB commit and publish → the message still goes out on restart.

## Phase 4 — NoSQL + Caching (~Week 7)

**[PLAN goal]** **DynamoDB** for idempotency store + seat-hold (atomic
conditional writes) — justify vs Postgres. **ElastiCache Redis** for
catalog cache + cloud seat-holds. LLD: repository abstraction over two
stores. HLD: RDS vs DynamoDB decision, partition/sort key design, GSI,
caching strategies (cache-aside), throttling.

**[PROPOSAL]:** don't rip out Postgres — add DynamoDB alongside for the
idempotency store first (natural fit: single-item conditional writes).
Then move the seat-hold to DynamoDB with atomic conditional writes and
compare with the Redis-SETNX approach Week 1 built. The comparison IS
the deliverable.

## Phase 5 — ECS Fargate + networking + RDS (~Weeks 8–9)

**[PLAN]** Containerize → **ECR** → **ECS Fargate**. **VPC**/subnets
(public+private)/SG/NAT, **ALB**, **Route53**, **RDS** Postgres
(Multi-AZ), **Secrets Manager** + **KMS**, IAM roles (task roles,
least-privilege). **Terraform** everything.
**[PLAN Failure]:** ECS task crash → ALB health check fails → task
auto-replaced.
**Note per your rule:** the actual AWS resource creation you'll do
yourself, I pair on Terraform + verification.

## Phase 6 — Serverless where it fits (~Week 10)

**[PLAN]** **Lambda** for ticket-PDF generation (S3 upload trigger) +
hold-expiry cleanup (scheduled). **EventBridge** for event routing.
**API Gateway** for a public endpoint. **Cognito** for user auth. HLD:
**when NOT to use Lambda** (cold start, long-running, high-throughput
steady load), serverless vs ECS.

## Phase 7 — Observability + Security (~Week 11)

**[PLAN]** **CloudWatch** logs/metrics/alarms, **X-Ray** tracing,
correlation IDs (already have the pattern), structured logging. IAM
least-privilege audit, KMS, rate limiting on booking endpoint.
**[PLAN Failure]:** "Booking API slow — find the latency" → trace via
X-Ray, fix.

## Phase 8 — CI/CD + Production hardening (~Week 12)

**[PLAN]** **GitHub Actions** → build → test → ECR → ECS deploy →
health check → rollback. Autoscaling (flash-sale spike = perfect
scenario), blue-green/canary, cost optimization, DR (Multi-AZ,
backups). Full portfolio README.

**[PLAN Job-loss readiness matrix]:**

| At end of… | Interview-ready for |
|---|---|
| Phase 1–2 | Mid/Senior backend |
| Phase 3–4 | Senior microservices |
| Phase 5–6 | Senior + cloud (SAA-eligible) |
| Phase 7–8 | Lead-track |

---

# TRACK B — NARRATION / GENAI (Jarvis GenAI Path)

## P1 close-out — Week 5 options (~this coming week)

P1 is already beyond its original Week 1 brief. Not committing to a
direction yet — pick ONE before starting:

- **Option A — Multi-provider fallback** (Gemini → OpenAI/Anthropic on
  outage). Introduces provider abstraction, provider-agnostic
  Instructor usage, and a real "when does fallback fire vs when
  should we just fail fast" design question. Fits P7 preview cleanly.
- **Option B — Structured metrics/observability**
  (Prometheus/OpenTelemetry). Aligns with ticketing Phase 7's
  observability. Same correlation-ID plumbing already exists.
- **Option C — Move on to P2**. P1 is complete enough; the honest next
  chapter is document RAG. My recommendation is **Option C** —
  fallback and metrics are P7-track concerns, P2 unlocks a whole new
  capability (documents, not just history).

## P2 — Transaction + policy RAG (~Weeks 5–7)

**[PLAN]** Documents, chunking, retrieval, citations. Python; S3;
modular monolith. HLD focus: "How do you design a RAG system?" (2026's
top AI system-design question).

**[PROPOSAL] Weekly split:**

- **Week 5 — Ingestion**
  - Day 1 — Upload endpoint for policy PDFs; store raw file in S3
    (LocalStack fine here since it's just PUT/GET; move to real S3
    later). Record a `Document` row.
  - Day 2 — PDF text extraction (pypdf or pdfplumber). Deliberately
    hit a broken/scanned PDF — you WILL find one — and design the
    error path (skip vs OCR vs fail loud). Write it up as a real
    finding, not a "we assumed PDFs are text."
  - Day 3 — Chunking. Not a fixed 500 tokens — pick an approach and
    justify it (paragraph-aware vs recursive-splitter vs sentence-boundary).
    Add a chunk table (`document_id`, `chunk_index`, `text`,
    `token_count`). Prove: a very short doc → 1 chunk; a very long doc
    → N chunks with correct offsets.
  - Day 4 — Embed each chunk (`gemini-embedding-001`, same as Week 3
    RAG). Store the vector. Reuse the SQLite + JSON-text approach or
    introduce pgvector — decision to be made on the day based on data
    volume; probably still SQLite for P2, pgvector arrives with P7.
  - Day 5 — End-to-end retrieval: query → embed → top-k chunks → return
    them with `document_id` + `chunk_index` for citations. NO LLM in
    the loop yet, just retrieval quality visible.

- **Week 6 — Grounded generation + citations**
  - Day 1 — Prompt design: system prompt that FORCES citations (the
    output schema includes a `citations: list[Citation]` field, each
    with `document_id`, `chunk_index`, `snippet`). Instructor + Pydantic
    enforces this — a model that answers without citations gets
    validation-rejected and retried.
  - Day 2 — Grounded answering endpoint (`POST /ask`). Real answer with
    real chunks pulled in.
  - Day 3 — Hallucination probe: ask questions the corpus DOES NOT
    answer. Does the model make things up? Does it correctly say "not
    in the corpus"? This is the honest measurement everyone skips.
  - Day 4 — Retrieval quality eval: hand-label 20 queries with the
    correct chunk id → measure recall@k. Report the real number, not a
    flattering cherry-pick.
  - Day 5 — Batch of failure experiments: empty corpus (answer must be
    "I don't know", not a hallucination), oversized query, adversarial
    prompt asking the model to ignore instructions.

- **Week 7 — Reranking + caching + polish**
  - Day 1–2 — Reranker layer (cross-encoder or a lightweight LLM call
    that re-orders top-k). Measure: does it actually improve
    recall@k on the eval set? Report null result if it doesn't.
  - Day 3 — Result cache keyed on (query embedding, top-k id set).
  - Day 4 — Docs & README, an updated architecture diagram, RAG design
    Q&A ("what if the corpus is 1M docs — what changes?").
  - Day 5 — Commit + push + companion HTML notes updated.

## P3 — Knowledge assistant (~Weeks 8–9)

**[PLAN]** Auth, memory, evaluation pipeline. Python; S3; modular
monolith. HLD: conversation memory, eval-as-a-system.

**[PROPOSAL headline]:** turn P2's `/ask` into a stateful
`/conversations/{id}/messages` chat. Design decisions: window vs summary
vs vector-recall memory (all three exist, each fits a different pattern).
Auth via a real JWT gateway. Eval pipeline becomes a first-class
subsystem, not a script — every deploy runs it, pass/fail metrics
committed.

## P4 — Async document processing (~Weeks 10–11)

**[PLAN]** Event-driven, idempotency, retries, backpressure. Python;
**SQS, S3, ECS/Lambda, CloudWatch**. **First real microservice split:
API + Worker.** HLD: async HLD, DLQ, exactly-once vs at-least-once,
backpressure.

**[PROPOSAL]:** ingestion becomes async. `/documents` returns 202 fast,
worker consumes from SQS and does chunk-embed-store. Idempotent by
`document_id`. Real DLQ, real backpressure story. Same design as
ticketing Phase 3 but for the doc pipeline — the patterns rhyme.

## P5 — Tool-calling assistant (~Weeks 12–13)

**[PLAN]** Tool loop + guardrails. Python **+ Spring AI port** (the
second and last Java port — this is the dual-capability differentiator).
Tool loop design, prompt-injection defence.

## P6 — Agentic dispute/reconciliation (~Weeks 14–15)

**[PLAN]** Agent loop + "when NOT to agent" decision. HLD: agent vs
plain RAG, loop control (max iterations, cost budget, timeout).

## P7 — Multi-model platform (~Weeks 16–18)

**[PLAN]** Routing, fallback, cost/latency, observability. **ECS/EKS,
RDS + pgvector, Secrets Manager, API Gateway, IAM.** HLD: capacity and
token-cost estimation, routing and provider fallback.
**Same-time cross-track note:** by now ticketing Phase 7 is running,
same observability primitives — deliberately share the story in the
final README.

## P8 — Capstone platform (~Week 19+)

**[PLAN]** Full production system. Both languages. Full CI/CD and full
architecture. The portfolio artifact.

---

# CROSS-TRACK CADENCE

- **Ticketing and Narration run side-by-side** (per `JARVIS_OPENAI_CONTEXT.md`),
  not sequentially. Alternate weeks by feel — the goal is to end each
  week with SOMETHING green on both tracks, not to sprint one and starve
  the other.
- Every week ends with:
  - README + LEARNING_NOTES.md prose updated (self-check Qs, no
    answers — revision material).
  - Companion HTML notes card added (`SEAT_LOCK.html` /
    `NARRATION_LAB.html`), republished to the Artifact link AND repo
    copy in sync.
  - Commit + push after your explicit OK — never reflexive.
  - You answer that week's interview Qs FIRST, then I evaluate.

## The one non-negotiable rule (per memory)

- Sole author on commits: **Rajat Agrawal <rajatagrawal2702@gmail.com>**.
  No `Co-Authored-By` trailer, no exceptions, regardless of what any
  tool-level default says.
