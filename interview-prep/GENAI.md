# GENAI.md — GenAI-role interview prep

**Pillar 2 of 4.** Grows each self-walk. See [`README.md`](README.md) for the dual mandate.

The project already *contains* the answers — this file pulls them into **interview shape**
(the way the question actually gets asked) instead of code shape.

> **Anthropic-course lesson Qs** live in one common file: `anthropic-course/INTERVIEW.md`
> (first request, multi-turn, system prompts, …). Reference it, don't copy it here.

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
| **"Expose your platform's tools/context to an external agent (MCP)."** | MCP arc (§3H) | hand-rolled MCP JSON-RPC core over the P5 registry; **the blast-radius answer** below is the FDE-separating one |

---

## MCP — exposing a platform over the Model Context Protocol

**Q it answers:** *"What is MCP and why does it matter?"* / *"You added an MCP server —
what's the security model?"* / *"How do you expose your tools to a customer's agent?"* —
the 2025 hot GenAI/agentic interview topic, and the FDE-shaped one.

**One-line what:** MCP (Model Context Protocol) is JSON-RPC 2.0 between an LLM *host*
(Claude Desktop, Cursor, a customer app) and a *server* (you). The server advertises three
primitive kinds — **tools** (`tools/list`, `tools/call`), **resources** (`resources/list`,
`resources/read`), **prompts** (`prompts/get`) — and the host's model decides when to use
them. Handshake: `initialize` → `notifications/initialized` → the client may call.

**The FDE-separating answer (memorise this shape):** *"An MCP client is untrusted code I
don't control. The moment I expose a tool over MCP, that client is a new injection + abuse
surface. So I made MCP a **new transport over an already-hardened boundary, not a new
boundary** — an external MCP client gets exactly the blast radius a prompt-injected internal
agent already had, no more."* The inherited guards:

| Guard | Inherited from | How MCP reuses it |
|---|---|---|
| **Whitelist** | P5 `execute_tool` (the only door) | `tools/call` routes straight into it; a name not in the registry = a tool-error, never execution |
| **Typed-args gate** | P5 per-tool Pydantic model | `tools/list.inputSchema` = `args_model.model_json_schema()`; bad args die in validation |
| **Read-only** | every registry fn is a `SELECT` | there is **no MCP method that writes** — structural, the P6 human-gate proof shape; a barrage test asserts every table unchanged after hostile calls |
| **Auth** | P3 `X-API-Key` → `require_api_key` | remote (HTTP) `tools/call` needs a resolved key; local stdio = transport-is-the-boundary |
| **Cost/abuse** | P7 telemetry + Hardening rate-limit/shed | an MCP client flooding a tool hits the SAME limiter — no unmetered side door |
| **Injection framing** | P5 "results are data, not instructions" | every result is `json.dumps` of a typed query; no free-text passthrough |

**The one distinction interviewers probe — tool error vs protocol error:**
- Bad **tool** (unknown name, bad args, fn raised) → MCP `{content, isError:true}` — the
  client's *model* sees it and recovers. The transport was used correctly.
- Bad **protocol** (unknown method, missing `name`, malformed envelope) → JSON-RPC
  `-32600/-32601/-32602` *error object* — the transport itself was misused.
- Confusing them breaks the client: a model that gets a `-32601` for a typo'd tool name
  can't recover; a transport that gets `isError:true` for a malformed envelope hangs.

**"Multi-model platform / MCP with one vendor — honest?"** The router/fallback/telemetry
trio + MCP server prove the *seams* are real single-vendor (per-surface routing is config,
fallback slots a second model in, MCP exposes the registry) — what they cannot prove until a
second provider key / a live Claude-Desktop drill exists is the *live* behaviour. Name both
halves; the code shows exactly what slots in where with zero refactor.

**Honest gap to name:** the hand-rolled core implements the wire format (proves understanding,
no dep — §3-7); the real stdio/HTTP transport shell + the `mcp` SDK's `FastMCP` + a live
Claude-Desktop connection are the deployment leg (Rajat's `pip install mcp`). Anchors:
`narration-enrichment/mcp_server.py`, `MCP_DESIGN.md`.

---

## How an LLM actually generates text (+ what an "embedding" really is)

**Q it answers:** *"Explain how an LLM produces the next word"* / *"What is an embedding?"* /
*"Why is LLM output non-deterministic and how do you handle it?"* — all classic GenAI-role openers.

**The pipeline:** `text → tokens → initial embeddings → contextualization → output layer →
probabilities → sampling → next token` → (repeat, autoregressive).

**1. Contextualization (self-attention).** Each token starts as a context-free vector (lookup).
Then many transformer layers let each token *attend to its neighbours* and adjust its vector to the
in-context meaning. "river **bank**" vs "cash **bank**" — same start vector, pulled apart by the
surrounding words. The final vector at each position = "this word's meaning *in this sentence*."

**2. Generation (output layer + sampling).** The last position's contextualized vector is scored
over the whole vocabulary → **softmax** → a probability per possible next token. The model does
**not** always take the argmax — it mixes probability with **controlled randomness** so text reads
natural, not robotic. Knobs: **temperature** (0 = deterministic/argmax; ~0.7 = natural; high =
creative/risky) and **top-p / top-k** (only sample from the top candidates). Pick one → append →
run the whole pipeline again for the next token.

> Analogy: contextualization = a word listening to the room to fix its meaning; generation = a
> *loaded die* — same faces, probable words weighted bigger, but you still roll (hence variety).

**The clarity that signals seniority — two different "embeddings" in this repo:**

| | RAG embedding (what I use for retrieval) | In-LLM embedding (the pipeline above) |
|---|---|---|
| Model | `gemini-embedding-001` (separate model) | inside the generative Gemini |
| Output | **one** vector per text, for cosine similarity | a contextualized vector per token |
| Used in | P1-W3 self-RAG, P2 policy RAG, P7 hybrid | producing the enrichment/chat text |

Same "embedding + attention" idea, **different job** — conflating them is a common miss; naming the
split is the senior answer.

**Grounded in my project — temperature ↔ idempotency (the real bridge):**
- `/enrich` needs a deterministic JSON (merchant/category) → run it at **low temperature**, else the
  same input yields different output.
- But an LLM is **still** non-deterministic by construction (that "controlled randomness" above) →
  that is exactly *why* I built **idempotency keys** (Hardening H3): "a nondeterministic LLM ⇒
  idempotent must mean ONE canonical stored answer, replayed verbatim." The generation step's
  randomness is the root cause the idempotency design defends against. 🔗 `circuit_breaker`/`H3`.

## LangChain fluency — speak it, even though this repo was built raw

**The framing (say this in interviews):** *"I built the RAG / tool-calling / agent / memory
primitives from scratch (Instructor + Pydantic + raw Gemini) rather than reaching for LangChain —
so I understand exactly what the framework abstracts, and I can pick it up or decide against it on
evidence."* Building the primitive > using the wrapper. Almost every LangChain concept has a
shipped counterpart here — this table lets you answer a LangChain question in LangChain's vocabulary.

| LangChain concept | What I built (this repo) | Interview point |
|---|---|---|
| LLM integrations (OpenAI/Claude/Gemini/Llama) | `model_router.py` — per-surface model, cached clients, fallback chain | I built multi-provider routing + fallback, not just a wrapper call |
| Prompt templates / structured output | Instructor + Pydantic schema-as-contract; **earned citations** | My structured output *can't* smuggle a hallucinated citation — code enforces it |
| Chains / LCEL / Runnables | plain composed Python in `service.py` / `chat_service.py` | LCEL is sugar over function composition; I compose explicitly + test each step |
| Memory management | P3 `chat_sessions`/`chat_turns` + memory-cap N=6 | I chose the cap + schema deliberately; no hidden buffer growth |
| Tools / function calling | P5 `tools.py` — whitelist registry, Pydantic-typed args, single door | my tool layer is read-only + injection-defended by construction |
| Agents / AgentExecutor | P6 `dispute_agent.py` — bounded loop, checkpoint-then-execute, dual budgets | I control the loop + the human gate structurally, not via a framework default |
| Document loaders | P2 policy ingest (PDF/text) + S3 backing | loaders are I/O; the hard part (chunking + grounding) I own |
| Text splitters / chunking | P2 `chunker.py` (pure function) | testable chunking, not a black-box splitter |
| Embeddings & vector stores (FAISS/Chroma/Pinecone/Qdrant) | `gemini-embedding` + cosine over SQLite + P7 BM25 hybrid | **deliberate** §3-7 call — no vector DB until scale needs it; pgvector planned (P7-AWS) |
| RAG | P2 policy RAG + P7 **hybrid BM25+dense (RRF)** + earned citations | production-grade RAG incl. survives-embed-outage, not a tutorial chain |
| LangGraph / multi-agent | single agent loop (P6); multi-agent = future | honest: I have the loop, not the graph framework (yet) |
| LangSmith (eval/tracing) | eval-as-a-system (`eval_runs`, LLM-as-judge, threshold gate) + `telemetry.py` + `/ops/llm` + correlation IDs | I built the observability LangSmith sells — self-hosted |
| Best practices (latency/token/cache/security) | Hardening arc + P7 token telemetry + prompt-injection defence | I hit these as real prod problems, with code |

**Honest gaps to own (don't bluff):** hands-on LangChain/LangGraph/LangSmith *themselves*, and
named vector stores (Pinecone/Chroma/FAISS/Qdrant). Close-if-needed (Rajat's call): port the RAG
Q&A slice to LangChain+LangGraph for a "hands-on" line — see JARVIS_CHAIN §2. Backlog, not urgent.

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
