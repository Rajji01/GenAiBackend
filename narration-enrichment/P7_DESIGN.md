# P7 Design — Multi-model platform (hybrid retrieval, telemetry, routing)

> **Day-1 deliverable for P7** (before any code). Same shape as the
> P2–P6 papers.
>
> **P7 goal (from `Jarvis_GenAI_Path.md`):** routing, fallback,
> cost/latency, observability. **Unit chosen under the JARVIS_CHAIN §2
> market-signal weighting:** the stash's derived priority order has two
> open items — #3 *hybrid search + re-rank* and #4 *token-cost
> telemetry + budget alert* — and both are P7-shaped. They anchor Days
> 2–3; routing/fallback (P7's title feature) lands Day 4 in its
> smallest honest form. The AWS half of P7's original brief (RDS +
> pgvector, Secrets Manager, API Gateway, ECS/EKS) is **[Rajat]'s** per
> rule 3-2 — named in §6, not silently dropped.

---

## Table of contents

1. [Why these three, in this order](#1-why-these-three)
2. [D2 — Hybrid retrieval: BM25 + dense + RRF](#2-hybrid-retrieval)
3. [D3 — LLM telemetry: cost/latency as first-class rows](#3-llm-telemetry)
4. [D4 — Model routing + fallback chain](#4-routing--fallback)
5. [Failure matrix](#5-failure-matrix)
6. [The [Claude]/[Rajat] boundary](#6-boundary)
7. [Interview questions](#7-interview-questions)

---

## 1. Why these three

- **Hybrid retrieval** attacks dense-only's known blind spot: EXACT
  lexical matches. A narration containing the literal token
  `NETFLIX` can lose to fuzzier neighbours under cosine, because
  embeddings trade surface form for meaning. BM25 sees the token;
  dense sees the meaning; production RAG uses both. Bonus that falls
  out structurally: **lexical retrieval needs no embedding call**, so
  retrieval now survives an embed-endpoint outage — an upgrade the
  chaos suite must pin.
- **Telemetry** is the ops half of "multi-model": you cannot route on
  cost/latency you don't measure. Every LLM call becomes a row
  (surface, model, latency, outcome, tokens, estimated cost) — the
  P3-invariant-4 shape (persist observability alongside expensive
  ops) applied to the most expensive op the system has.
- **Routing + fallback** then has something to stand on: per-surface
  model choice in config, and a bounded fallback chain for the one
  failure class where a second model genuinely helps (primary's
  transient exhaustion — NOT an open circuit, see §4).

---

## 2. Hybrid retrieval

### BM25, pure Python (rule 3-7)

`bm25.py`: Okapi BM25 (k1=1.5, b=0.75) over a corpus built per query
from the SAME rows the dense path reads (narrations / policy chunks).
Tokenizer: lowercase alphanumeric split — bank narrations are
`UPI/NETFLIX/Payment` strings; splitting on non-alnum IS the
domain-right tokenizer, not a shortcut. No index persistence: at this
scale (hundreds of rows) scoring per query is microseconds; an
inverted index is flagged as the at-scale move, not built.

### Fusion: Reciprocal Rank Fusion, not score mixing

Dense cosine (0..1) and BM25 (unbounded) live on incomparable scales —
mixing raw scores needs per-corpus calibration that drifts. **RRF**
(`score = Σ 1/(k + rank)`, k=60) uses only RANKS: scale-free, stable,
and the standard first answer. The fused score is what goes into
`Citation.similarity_score` for policy chunks — citations stay earned,
now by the fused ranking that actually chose the chunk.

**This is the re-rank for now, honestly:** a true cross-encoder
re-ranker is another model call per candidate — cost without evidence
at this corpus size. Flagged as the eval-gated next step (add when
recall@k on the golden set says the boring version is losing).

### Wiring

`hybrid_find_similar_examples` / `hybrid_retrieve_policy_chunks` in
rag.py: run dense (when an embedding is available) + BM25, fuse by
RRF, apply the existing floors to the DENSE component only (BM25 has
no comparable floor; an RRF floor is meaningless across corpus sizes)
— a candidate enters fused ranking if it clears EITHER channel's
entry bar (dense floor / BM25 score > 0). `query_embedding=None` ⇒
lexical-only — the degrade path, not an error.

---

## 3. LLM telemetry

### The table

```python
class LlmCall(Base):
    id            : int PK
    surface       : str   # 'enrich' | 'chat' | 'dispute_agent' | 'dispute_judge'
    model         : str
    latency_ms    : int
    outcome       : str   # 'ok' | 'provider_down' | 'error'
    prompt_tokens : int | None     # real usage when the SDK exposes it
    completion_tokens : int | None
    est_cost_usd  : float | None   # None when tokens unknown — never a fake 0
    created_at    : datetime
```

- **Written by the call wrapper itself, non-fatally** (its own short
  session; a telemetry DB hiccup must never fail the user's request —
  the run_eval persistence precedent).
- **Real token counts where the SDK gives them** (`usage_metadata` via
  Instructor's `create_with_completion` on the enrich + chat
  surfaces); the dispute surfaces record latency/outcome with tokens
  None this arc — flagged, not faked. `est_cost_usd` only when tokens
  exist, from a PRICE_TABLE in config whose header says prices drift
  and the number is an ESTIMATE for budget math, not billing.

### `/ops/llm` + the budget alert (signal #4)

Auth-gated rollup: per-surface calls / ok-rate / p50+p95 latency
(computed in Python over today's rows — fine at this volume, flagged
for percentile-sketches at scale), tokens today, estimated spend
today, and `budget: {daily_limit_usd, spent_est_usd, exceeded}`.
Crossing the limit logs `llm_budget_exceeded` — the alert is a log
line an operator can page on; a pager integration is not this repo's
job. The budget NEVER blocks calls (that's the rate limiter's job,
on a signal it can actually trust); it observes and shouts.

---

## 4. Routing + fallback

### Routing: per-surface model choice, config-driven

`model_router.py`: `model_for(surface)` reads `MODEL_ENRICH` /
`MODEL_CHAT` / `MODEL_DISPUTES` (all default to today's single model).
The ROUTE is data, not code — moving chat to a bigger model is an env
change. One Instructor client per model, built lazily and cached.

### Fallback: one secondary, one narrow trigger

`FALLBACK_MODEL` (default empty = off). When set, a call whose
primary attempt exhausts as **provider-down** (the
`counts_as_provider_down` whitelist) is retried ONCE on the fallback
model. Narrow on purpose:

- **An open circuit does NOT consult the fallback.** The breaker says
  "the PROVIDER is down" — both models live behind the same provider
  endpoint/key here, so routing to a sibling model during an outage is
  a retry storm with a costume on. Fallback answers a different
  question: "the primary MODEL is overloaded/unavailable right now."
- Fallback attempts are telemetry rows like any other (model column
  tells the story), and a fallback success records breaker-success —
  the provider demonstrably answered.
- A SECOND provider (different vendor, different key) is the real
  multi-provider story; it slots into the same chain but needs
  Rajat's keys — §6.

---

## 5. Failure matrix

| Failure | Behavior | Rule |
|---|---|---|
| Embed endpoint down | Retrieval degrades to BM25-only; /enrich + /chat keep real (lexical) context — UPGRADED from empty-context | degrade-not-fail, now with teeth |
| Dense finds nothing, BM25 finds exact token | Candidate enters fused ranking via the lexical channel | the blind spot this day exists for |
| Telemetry DB write fails | Request unaffected; one warning log | observability never fails the op |
| SDK returns no usage metadata | tokens None, est_cost None | None, never fake 0 (the /stats rule) |
| Daily budget crossed | `/ops/llm.budget.exceeded=true` + one log/alert; calls continue | observe-and-shout, don't double-police quota |
| Primary model transient-exhausted, fallback set | ONE fallback attempt; both attempts in telemetry | §4's narrow trigger |
| Circuit OPEN | Fast 503 as today; fallback NOT consulted | same provider = same fate |
| Fallback also fails | Original error propagates (503 shape unchanged) | bounded chain, no wandering |

---

## 6. The [Claude]/[Rajat] boundary

| Item | Who |
|---|---|
| bm25/RRF, telemetry table + /ops/llm, router/fallback, all tests | **[Claude]** |
| pgvector on RDS (dense index at scale), Secrets Manager for keys, API Gateway, ECS deploy | **[Rajat]** — P7's AWS half; Terraform can be authored on his go |
| A real second PROVIDER (other vendor key) in the fallback chain | **[Rajat]** (keys) — the chain is built to take it |
| Live recall@k eval of hybrid vs dense-only on the golden set | **[Rajat]'s quota** (rule 3-6) — code-side eval math ships, the live numbers are his run |

---

## 7. Interview questions

1. **Why does dense retrieval miss exact tokens** (mechanically — what
   does the embedding do to `NETFLIX` that BM25 doesn't), and why is
   RRF the standard fusion instead of weighted score addition? What
   breaks with score mixing?
2. **The BM25 floor question:** the design applies the similarity
   floor to the dense channel only. Why is a floor on BM25 scores
   across corpora meaningless, and what plays the entry-bar role on
   the lexical side?
3. **Token telemetry:** why must `est_cost_usd` be None (not 0) when
   usage is missing, and why does the budget alert observe-and-shout
   instead of blocking calls? Which existing mechanism would blocking
   duplicate badly?
4. **Defend "an open circuit does not consult the fallback"** — and
   state exactly what has to change about the DEPLOYMENT (not the
   code) before that rule should flip.
5. **p50/p95 in Python over today's rows:** at what volume does this
   lie or fall over, and what replaces it (sketches? histogram
   buckets? OTel)? What do you lose in each replacement?
6. **"Multi-model platform" with one vendor key — is this honest?**
   Argue what the router/fallback/telemetry trio proves even
   single-vendor, what it cannot prove until a second provider key
   exists, and how the code shows the seam is real (what slots in,
   where, with zero refactor).

---

*Plan lives in `ROADMAP.md` §3G. Live legs (recall@k, budget drill,
second provider, AWS half) are Rajat's — rules 3-2/3-6.*
