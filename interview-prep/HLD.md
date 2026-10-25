# HLD.md — High-Level Design (system design) prep

**Pillar 3a of 4.** Grows each self-walk. See [`README.md`](README.md) for the dual mandate.

Each project phase already produces an HLD artifact (design paper + trade-off table). This
file turns them into **rehearsable whiteboard walkthroughs** — the shape an interviewer draws.

---

## The walkthrough index (each = a 30-min whiteboard answer)

| # | Prompt (how it's asked) | Source paper | Status |
|---|---|---|---|
| H1 | **"Design a RAG system."** | P2_DESIGN + P7_DESIGN | walkthrough drafted below |
| H2 | **"Design an async document-processing pipeline."** | P4_DESIGN | stub — next HLD walk |
| H3 | **"Design an agentic workflow with a human in the loop."** | P6_DESIGN | stub |
| H4 | **"Design a multi-model LLM gateway (routing + fallback + cost)."** | P7_DESIGN | stub |
| H5 | **"Design the cloud footprint (VPC/ECS/RDS/ALB/Secrets)."** | WEEK4_DESIGN (ticketing) | stub |
| H6 | **"Make an LLM app survive production."** (failure modes) | PROD_HARDENING | stub |
| H7 | **"Design a URL shortener (TinyURL)."** | — (classic) · echoes P2 checksum-idempotency | stub — MobiKwik signal 2026-10-25 |
| H8 | **"Service hit by 10× traffic and failing — stabilize + scale."** | **≈ the whole Hardening arc (P5.5)** + P4 async + P7 fallback | ✅ **drafted below** — MobiKwik signal 2026-10-25 |

> **H8 is the one to draft first** (MobiKwik Q4). It's the §3-12 Job A question in interview
> form, and ~all of it is already built: **immediate** — load-shed, rate-limit, circuit-break,
> scale-out, cache the hot path; **diagnose** — dashboards (`/stats`, `/ops/ingest`, `/ops/llm`,
> correlation IDs) to find *which* layer (DB pool? token budget? p99?); **structural** — offload
> heavy work to an async queue (P4), autoscale, DB read-replica + connection-pool tune, kill the
> retry storm (whitelist-only + backoff + breaker). Same story = the FDE "it broke at their 3am."
>
> **H7 (URL shortener)** key beats: base62(counter) vs hash+collision-check, a key-gen service,
> read-heavy ⇒ cache + CDN + 301/302, DB choice + sharding, custom alias, analytics, capacity math.

---

## H1 — "Design a RAG system" (the drafted one)

**1. Clarify (always first).** Corpus size? Freshness? Latency budget? Grounding/compliance
requirement? Cost ceiling? → fintech framing: compliance-grade grounding, modest corpus, p95 < Ns.

**2. Core path.** ingest → chunk → embed → store → retrieve → rerank → prompt-weave → generate → cite.

**3. The decisions that signal seniority:**
- **Chunking** — size vs overlap vs semantic; why pure-function chunker (testable). (P2 D2)
- **Store** — SQLite+cosine now (don't overengineer, rule §3-7); pgvector when scale demands (P7). *Say why you DIDN'T reach for a vector DB on day 1.*
- **Hybrid retrieval** — BM25 (exact tokens, survives embed outage) + dense (semantic), **RRF-fused by rank not score**. The exact-token blind spot of pure-dense is the money point. (P7 D2)
- **Grounding** — **earned citations**: code overwrites LLM citations from ground truth. (P2 D5)
- **Eval** — golden set + LLM-as-judge + threshold gate; deploy gated on pass-rate. (P6)

**4. Failure modes** (the part juniors skip): embed endpoint down → hybrid degrades to lexical,
still 200. Retrieval empty → honest "I don't have a policy on that," never hallucinate. Token
spend spike → budget telemetry shouts. (Hardening + P7)

**5. Scale story.** corpus 10×: pgvector + ANN index; QPS 10×: cache embeddings + semantic cache;
cost 10×: route cheap model for easy queries, reserve strong model (P7 routing).

**Trade-off table to draw:** sync-vs-async retrieval, dense-vs-hybrid, SQLite-vs-pgvector,
one-model-vs-routed — each with "I chose X because the requirement was Y."

---

## H8 — "Service hit by 10× traffic and failing — stabilize + scale" (drafted, MobiKwik Q4)

This is the **§3-12 Job A question in interview form**, and almost every lever below is already
built in this repo — so the answer is "here's what I did," not theory. Answer in **three phases**,
in order — interviewers want to see you stop the bleeding *before* you redesign.

**0. Clarify first (10 seconds, signals seniority).** "Failing *how* — timeouts, 5xx, OOM, DB
pool exhausted, or an upstream (LLM/provider) choking? Is it uniform or one endpoint? Is it real
users or a retry storm amplifying itself?" The fix depends on the answer; naming that is the point.

**Phase 1 — STABILIZE (minutes, no deploy): protect the core, shed the rest.**
- **Load-shed at the door.** Bounded in-flight counter → overflow returns a microsecond `503 +
  Retry-After`, never a slow death. *(built: `load_shed.py` — cap 8, finally-released on every
  path.)* A fast 503 beats a queue that melts the box (metastable failure).
- **Rate-limit per client** so one caller can't eat the budget. *(built: `rate_limiter.py` sliding
  window.)*
- **Circuit-break the failing dependency.** If the LLM/DB is the choke, OPEN the breaker → instant
  503 instead of piling threads on a dead upstream; HALF_OPEN admits one probe to test recovery.
  *(built: `circuit_breaker.py`, trips only on the transient whitelist.)*
- **Kill the retry storm.** Retries only on 429/503/504 + timeouts, with backoff — never a blanket
  retry (that's what turns 10× into 50×). *(built: the whitelist rule, both tracks.)*
- **Scale out the stateless tier** (more ECS/Fargate tasks behind the ALB) — works precisely
  *because* the API tier holds no session state.
- **Protect writes with idempotency** so client retries during the storm don't double-process.
  *(built: idempotency keys on `/enrich`, replay stored bytes.)*
- The ordering is pinned: **replay → shed → quota(429) → breaker(503)** *(Hardening H4)*.

**Phase 2 — DIAGNOSE (which layer is actually the wall?).** Don't guess — read the dashboards:
- `/stats`, `/ops/ingest`, `/ops/llm` (queue depth, DLQ, **token spend**, p-latencies) +
  **correlation IDs** to trace one failing request end-to-end. *(all built.)*
- Classic walls, in likelihood order: **DB connection pool** exhausted → **token/cost budget**
  blown → **p99 on the sync LLM call** → thread pool → memory. Name the metric that proves each.

**Phase 3 — SCALE STRUCTURALLY (the redesign, once stable).**
- **Offload heavy work to async.** Anything slow/spiky (embeddings, LLM) → 202 + queue + worker
  pool that scales independently; the API stays fast. *(built: P4 API+Worker split, SQS, DLQ,
  recovery sweep, backpressure.)* This is *the* answer to "spiky heavy workload."
- **Cache the hot read path** (+ semantic cache for repeated LLM queries — backlog in `GENAI.md`).
- **DB:** read-replicas for read-heavy load, tune the pool, add the missing index, shard if truly
  needed (don't prematurely — §3-7).
- **Autoscale on the real signal** (queue depth / CPU / in-flight), not vanity metrics.
- **Degrade, don't die:** hybrid retrieval survives an embed outage; a fallback model chain covers
  provider-down. *(built: P7 D2/D4.)* A degraded 200 beats a 500.

**Trade-off to voice:** shedding load = *intentionally* failing some requests to keep the rest
alive and fast — availability-of-the-whole over success-of-every-request. That honesty is the
senior signal.

**FDE bridge:** this is verbatim the "it broke at the customer's 3am" story — same levers, plus
"here's the dashboard and runbook I'd hand their on-call." See `FDE.md`.

---

## HLD estimation drills (backlog — build one per walk)
- "**10k enrichments/day → token cost/month → which model where?**" (ties FDE cost model + P7)
- "**p99 latency budget** for the sync `/enrich` path — where does it go?"
- "**Queue depth math** — ingest spike of 100k docs, worker throughput, DLQ rate, drain time." (P4)
