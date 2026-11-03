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
| **S3** | **"The customer wants their OWN AI agent (Claude Desktop / a copilot they're building) to query our platform — not use our UI."** | MCP arc (§3H) | **drafted 2026-11-03** ↓ |
| _…_ | _next walk adds one_ | | |

### S3 — "expose the platform to the customer's own agent" (the MCP/FDE scenario)

> *A fintech customer says: "we don't want to live in your dashboard — we're building our own
> internal copilot, and we want IT to be able to ask 'how many disputed Swiggy charges this
> month' and pull our policy rulebooks. Give our agent access."*

This is the **2025 FDE-shaped MCP question**, and the answer is a trust-boundary story, not a
feature list:

1. **The protocol is the easy part.** We speak MCP (Model Context Protocol) — their Claude
   Desktop / Cursor / custom app connects to our server, discovers our tools + policy resources,
   and their model calls them. One `claude_desktop_config.json` entry on their side. *(Anchor:
   `mcp_server.py`, `MCP_DESIGN.md`.)*
2. **The real question is blast radius — and that's where I lead.** "Your agent is code I don't
   control; the moment I expose a tool to it, it's a new injection + abuse surface." So I made
   MCP a **new transport over an already-hardened boundary, not a new boundary**: their agent
   gets exactly what a prompt-injected internal agent gets — read-only whitelisted tools (it can
   COUNT and FIND, it cannot ingest/dispute/approve/delete — there is no MCP method that writes,
   proven by a barrage test), typed-args validation, their own `X-API-Key` identity, and the
   SAME rate-limiter/load-shedder (their agent looping a tool 10k times gets throttled like any
   client — no unmetered side door). *FDE point: "can their agent do the dangerous thing?" is
   the first question their security team asks — and the answer is structural, not a promise.*
3. **Cost is their cost.** Every MCP call is visible in `/ops/llm` telemetry per key — so when
   their agent's bill spikes, we can both see which tool, which key, which day.
4. **The honest edge.** The hand-rolled core proves I understand the wire format; the real stdio/
   HTTP transport + a live Claude-Desktop drill is the deployment step we'd do together in the
   embed. *FDE point: name what's shipped vs what's the go-live checklist — don't oversell.*

**Why this is a strong FDE signal:** it's the exact 2025 "integrate our AI into the customer's
AI" ask, and it shows product-sense (they need API/agent access, not another UI) + security
instinct (blast radius first) + honest scoping — the three things the interview actually tests.

## Open FDE angles to build (backlog)
- A one-page **"customer runbook"** artifact (what the customer's on-call sees + does).
- A **cost model**: "10k enrichments/day → token cost → which model routes where" (ties to P7 routing + `/ops/llm`).
- The **demo script** — the literal click-path that shows value in 5 minutes.
- "**Customer asked for X but needs Y**" story (product-sense signal) — mine one from a real design decision in the repo.
