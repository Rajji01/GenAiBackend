# GENAI.md — GenAI-role interview prep

**Pillar 2 of 4.** Grows each self-walk. See [`README.md`](README.md) for the dual mandate.

The project already *contains* the answers — this file pulls them into **interview shape**
(the way the question actually gets asked) instead of code shape.

> **No duplication:** the granular per-day Qs live in
> `narration-enrichment/NARRATION_STUDY.html` (rule §3-11). This file holds the **big,
> cross-cutting, "design/debug this" questions** an interviewer actually opens with, and
> links down to the STUDY entries for detail.

---

## Topic map — what's asked ↔ what's built

| Interview topic (how it's asked) | Built in | The crisp answer anchor |
|---|---|---|
| **"How do you get structured output reliably from an LLM?"** | P1 | Instructor + Pydantic schema as the contract; retry only on malformed; the `InstructorRetryException`-wraps-everything bug (live-caught) → inspect `__cause__`, not the blanket |
| **"Design a RAG system."** (2026's #1 AI system-design Q) | P1-W3, P2, P7 | self-RAG → policy RAG w/ chunking + **earned citations** → **hybrid BM25+dense, RRF-fused**; retrieval survives an embed outage |
| **"How do you stop hallucinated citations?"** | P2 D5, P3 D4 | earned-not-decorated: code overwrites LLM-provided citations from ground truth; regression-tested on both surfaces — the LLM *cannot* smuggle one past the code |
| **"How do you evaluate an LLM app / gate a deploy?"** | P2/P3/P6 | golden dataset → eval-as-a-system (`eval_runs`/`/eval/history`) → **LLM-as-judge** + **fail-closed threshold gate** (exit 1 on fail); the judge's judge = divergence rate |
| **"Tool / function calling — design + guardrails."** | P5 | whitelist registry, Pydantic-typed args as the gate, bounded loop + forced-final, **no tool sums money**, earned tool-trail, prompt-injection = data-not-instructions framing |
| **"When do you reach for an agent — and when NOT?"** | P6 | the 3-condition when-NOT-to-agent framework (P4 ingestion is the deliberate counter-example); checkpoint-then-execute; dual budgets; safe-default-escalate; structural human gate |
| **"Multi-model / routing / cost."** | P7 | per-surface model via config; narrow fallback chain (fires only on provider-down); open circuit skips fallback; token telemetry + budget shout |
| **"Async ML pipeline / idempotency / exactly-once."** | P4 | API+Worker split; job-row-is-truth + message-is-hint; CAS claim = idempotent consumer; retry budget → DEAD; DLQ vs DB-DEAD; recovery sweep; backpressure |
| **"Observability for an LLM app."** | P1/P4/P7 | correlation IDs (ContextVar); `/stats`, `/ops/ingest`, `/ops/llm`; token-spend telemetry; PII-at-DEBUG; degrade-not-fail everywhere |
| **"Production failure modes for LLM systems."** | Hardening (P5.5) | 10-class catalog (retry storm, metastable overload, poison pill, dual write, gray failure…) → circuit breaker, idempotency keys, load shedding, chaos suite |

---

## The "tell me about a hard bug" bank (real, live-caught — gold in GenAI interviews)
1. **`InstructorRetryException` masked an exhausted 503 as a 422** — fix inspects `exc.__cause__`. (P1-W3)
2. **`.env`-at-import broke a fresh clone** — 12 test files died collecting; `conftest` placeholder fix. (portability)
3. **`Logger.addFilter` vs `Handler.addFilter`** — correlation ID silently absent. (P1-W4)
4. **mention-vs-call in the AST human-gate test** — assert on AST semantics, not source strings. (P6 D4)

→ Each deserves a full STAR write-up. Backlog: expand one per GenAI walk.

## Open GenAI angles to build (backlog)
- **RAGAS / faithfulness metrics** — read + wire one eval case (named in the §2 derived topic-map).
- **Semantic caching** story (cost lever) — concept + where it'd slot.
- **Streaming (SSE)** responses — latency-perceived win; where it'd slot in `/chat`.
- A crisp **"embeddings: why 256-dim, why cosine, why task_type asymmetry"** card (P1-W3 detail).
