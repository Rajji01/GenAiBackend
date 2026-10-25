# FDE.md — Forward Deployed Engineer prep

**Pillar 1 of 4.** Grows each self-walk. See [`README.md`](README.md) for the dual mandate.

---

## What an FDE actually is (so prep aims right)

Forward Deployed Engineer (Palantir-origin; now OpenAI / Anthropic / most AI startups).
Core loop: **embed with a customer → understand their messy domain → deploy the platform
on their real data → bridge product/eng/customer.** Interviewers test:

1. **Systems + practical coding** (not always hard DSA — solid, fast, correct).
2. **Product + customer sense** — "the customer actually needs X, not the Y they asked for."
3. **Ambiguity + data wrangling** — real data is dirty, under-specified, huge.
4. **Communication / demo** — can you explain a trade-off to a non-engineer and show it working?

**Why Rajat's narration platform is a strong FDE story:** it's not a toy chatbot — it's a
transaction-enrichment + policy-RAG + agentic-dispute platform with eval gates, async
ingestion, circuit breakers, idempotency, and observability. That is *exactly* the shape of
"a platform you deploy at a customer." The FDE pitch writes itself: **"here's how I'd stand
this up for a fintech customer."**

---

## The anchor scenario (the one to rehearse cold)

> **"A mid-size fintech wants transaction enrichment + a dispute-handling assistant on their
> own statement data and their own policy PDFs. Deploy our platform for them."**

Walk it as an FDE would, in this order (each maps to real code already built):

1. **Ingest their mess.** Their statements aren't my clean DTOs — wrong currencies, missing
   merchant fields, 10× volume, PDF scans. → P4 async pipeline (API returns 202 + job row;
   worker does the heavy embed/LLM), 3-layer idempotency so a retried upload never double-charges
   effort, DLQ for poison rows. *FDE point: the customer's data decides the architecture, not mine.*
2. **Their policies, their citations.** Their refund/chargeback PDFs → P2 policy RAG, chunk +
   embed, **earned citations** (the LLM physically cannot cite a policy that wasn't retrieved).
   *FDE point: in fintech, an un-grounded answer is a compliance incident, not a bad UX.*
3. **The assistant + the agent.** Grounded chat (P3) + tool-calling (P5, read-only whitelist —
   no tool sums money) + agentic dispute workflow (P6) with a **structural human gate** (the agent
   cannot approve a refund; proven 3 ways incl. an AST tripwire). *FDE point: "the agent can't do
   the dangerous thing" is the first question a fintech asks.*
4. **Prove it before go-live.** LLM-as-judge eval + fail-closed threshold gate (P6) → deploy is
   *gated* on eval pass-rate. *FDE point: this is how you earn the customer's trust to ship.*
5. **Operate it.** Correlation IDs, `/stats`, `/ops/ingest`, `/ops/llm` (token spend + budget
   shout), circuit breaker, load shedding. *FDE point: when it breaks at their 3am, here's the
   dashboard and the runbook.*
6. **Their ceilings.** Cost (token budget telemetry), latency (sync path hardened, async for heavy),
   availability (hybrid retrieval survives an embed outage; fallback model chain). *FDE point:
   every customer has a cost ceiling and an SLA — name them, design to them.*

**Rehearse:** be able to give this as a 3-minute pitch AND a 30-minute deep-dive.

---

## FDE scenario bank (grows each walk)

| # | Scenario | Maps to | Status |
|---|---|---|---|
| S1 | Deploy enrichment+dispute platform for a fintech (the anchor, above) | P2/P3/P4/P5/P6 | drafted 2026-10-25 |
| S2 | Customer's data is 10× dirtier than demo — how do you not lose rows? | P4 idempotency + DLQ + sweep | stub — expand next FDE walk |
| _…_ | _next walk adds one_ | | |

## Open FDE angles to build (backlog)
- A one-page **"customer runbook"** artifact (what the customer's on-call sees + does).
- A **cost model**: "10k enrichments/day → token cost → which model routes where" (ties to P7 routing + `/ops/llm`).
- The **demo script** — the literal click-path that shows value in 5 minutes.
- "**Customer asked for X but needs Y**" story (product-sense signal) — mine one from a real design decision in the repo.
