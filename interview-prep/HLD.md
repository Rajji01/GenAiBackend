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

## HLD estimation drills (backlog — build one per walk)
- "**10k enrichments/day → token cost/month → which model where?**" (ties FDE cost model + P7)
- "**p99 latency budget** for the sync `/enrich` path — where does it go?"
- "**Queue depth math** — ingest spike of 100k docs, worker throughput, DLQ rate, drain time." (P4)
