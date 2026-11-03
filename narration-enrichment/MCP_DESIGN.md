# MCP arc design — the platform speaks MCP (untrusted transport, same guards)

> **Day-1 deliverable for the MCP arc (§3H)** — an advanced
> capability-exposure arc on top of P7, chosen on a self-walk under the
> §3-12 dual mandate (Rajat: "real-time latest techniques — RAG, MCP,
> LangGraph… jo FDE kaam karenge, normal devs se alag"). Same
> paper-first discipline as P2–P7.
>
> **What this is:** the narration platform already has a clean,
> whitelisted, read-only, typed-args tool registry (P5 `tools.py`) and a
> policy corpus (P2). An agent OUTSIDE this process — a Claude Desktop,
> a customer's own LLM app, any MCP client — cannot use any of it. MCP
> (Model Context Protocol, the 2025 JSON-RPC standard for exposing
> tools/resources/prompts to LLM clients) is the missing layer. This arc
> adds it.

---

## 0. The thesis (why this is an FDE-differentiating build, not `@tool` sugar)

Most "I added MCP" work is: decorate three functions, run a server, done.
The interview-separating version asks the question a Forward-Deployed
Engineer at OpenAI/Anthropic/Google asks the moment a platform is
exposed to a **customer's** agent:

> *An MCP client is untrusted code I don't control. The moment I expose
> a tool over MCP, that client is a new injection + abuse surface. What
> blast radius does it get?*

The answer this arc enforces: **an external MCP client gets EXACTLY the
blast radius a prompt-injected internal agent already got — no more.**
Same whitelist (`execute_tool` is still the only door), same typed-args
gate (Pydantic validation still runs), same read-only guarantee (every
registered fn is a pure query), same auth (the P3 `X-API-Key` identity),
same cost accounting (every MCP tool call is an `LlmCall`-adjacent op in
telemetry), same injection framing (results are data, never instructions).
MCP is a **new transport over an already-hardened boundary**, not a new
boundary. That sentence is the whole arc.

This is the §3-12 Job A move: the "customer's dirty/hostile client" is
just another untrusted upstream, and the hardening discipline already
built (P5 whitelist, P6 structural gates, Hardening arc) extends to it.

---

## 1. What MCP is, in one screen

MCP is JSON-RPC 2.0 between an **LLM client** (host: Claude Desktop,
Cursor, a custom app) and a **server** (us). The server advertises three
primitive kinds; the client's model decides when to use them:

| Primitive | MCP methods | Our mapping |
|---|---|---|
| **Tools** | `tools/list`, `tools/call` | the P5 `TOOL_REGISTRY` (count / breakdown / find / list_policy_docs) — read-only queries |
| **Resources** | `resources/list`, `resources/read` | the policy corpus (P2) — each ingested doc is a readable resource (`policy://<doc_id>`) |
| **Prompts** | `prompts/list`, `prompts/get` | the enrichment task as a reusable prompt template (optional, Day 4) |

Plus the handshake: `initialize` (capability negotiation) → `initialized`
notification → the client may then call the above.

**Transport:** the spec's canonical transports are stdio (local, Claude
Desktop) and streamable HTTP (remote). This arc builds the **protocol
core** — the JSON-RPC dispatch + the three primitives' request/response
shapes — as a pure, testable `handle_message(dict) -> dict|None`. The
stdio/HTTP wire loop + the official `mcp` SDK's `FastMCP` wrapper are the
thin deployment shell and are **[Rajat]'s `pip install mcp` leg** (§6) —
named, not faked. Hand-rolling the core is deliberate: it proves wire-
format understanding (not decorator magic) and keeps the dep out (§3-7).

---

## 2. The protocol core — `mcp_server.py`

One pure function is the whole server logic:

```
handle_message(db, request: dict, *, api_key_hash: str | None) -> dict | None
```

- Parses a JSON-RPC 2.0 envelope (`jsonrpc`, `id`, `method`, `params`).
- Dispatches on `method`. Returns a JSON-RPC response dict (or `None`
  for notifications like `initialized`, which get no reply — a real
  wire-format detail the tests pin).
- Every error is a JSON-RPC error object (`code`, `message`), never a
  raised exception across the boundary — a malformed client message is
  the client's bug, answered with `-32600 Invalid Request` / `-32601
  Method not found` / `-32602 Invalid params`, the system stays up
  (degrade-not-fail, protocol edition).

### `initialize`
Returns `protocolVersion`, `serverInfo`, and `capabilities: {tools:{},
resources:{}}`. Capability negotiation is honest: we only advertise what
we actually serve.

### `tools/list`
Rendered **from `TOOL_REGISTRY`** — `{name, description, inputSchema}`
where `inputSchema = args_model.model_json_schema()`. The same
single-source rule as `catalog_block()`: the MCP tool menu and the
executor's whitelist **cannot drift**, because both read the registry.
Add a tool to the registry → it appears over MCP automatically, already
validated, already read-only.

### `tools/call`
`params = {name, arguments}` → straight into **`execute_tool`** (P5's
only door). The MCP result wraps the existing `ToolOutcome`:
- `ok=True` → MCP `{content:[{type:"text", text:<json>}], isError:false}`
- `ok=False` (unknown tool / invalid args / runtime fail) → MCP
  `{content:[...], isError:true}` — an MCP *tool error* (the model sees
  it and recovers), NOT a JSON-RPC protocol error (the transport is
  fine). This distinction is load-bearing and tested: a bad tool name
  is a tool-level `isError:true` with the menu named, not a `-32601`.

**The read-only guarantee is structural, inherited:** there is no MCP
method that writes. `tools/call` can only reach registry fns, every one
of which is a `SELECT`. An MCP client cannot ingest, dispute, approve,
or delete — those routes are not tools and MCP has no door to them. Same
"the capability simply doesn't exist in the reachable surface" proof as
P6's human gate.

---

## 3. Auth + cost (the untrusted-transport guards) — Day 4

- **Auth:** remote MCP (HTTP) reuses `X-API-Key` → `require_api_key` →
  `api_key_hash` threaded into `handle_message`. `tools/list` may be
  open (capability discovery leaks nothing — the registry names aren't
  secret, P5 rule), but `tools/call` requires a resolved key. Local
  stdio (single trusted user on their own machine) can run keyless — the
  transport IS the auth boundary there, documented.
- **Cost:** every `tools/call` is cheap (a DB query, no LLM) — but the
  arc wires an `mcp` surface into telemetry so an operator can see
  *who's calling what over MCP* and rate-limit a greedy client. An MCP
  client that loops `count_transactions` 10k times hits the SAME rate
  limiter / load shedder the HTTP path has — the untrusted client does
  not get an unmetered side door.
- **Injection:** `tools/call` results are returned as MCP `text` content
  — data to the client's model, framed by the client. We cannot control
  the client's prompt, but we guarantee our side never returns an
  instruction dressed as a result: every result is `json.dumps(outcome
  .result)` of a typed query, no free-text passthrough.

---

## 4. Day plan + DoD (mirrors ROADMAP §3H)

- **H-MCP Day 1 (this paper)** — the design + threat model + DoD.
- **Day 2** — `mcp_server.py`: JSON-RPC dispatch + `initialize` +
  `tools/list` + `tools/call` over the registry, error taxonomy, tests.
- **Day 3** — `resources/list` + `resources/read` over the policy
  corpus (`policy://<doc_id>`), + the FDE interview deposit.
- **Day 4** — auth + telemetry wiring (the untrusted-transport guards) +
  optional `prompts/` primitive + README "MCP server" section +
  LAB/STUDY/ROADMAP/AGENTS/CHAIN closeout.
- **Open after the arc (named, not hidden):** the real transport shell
  (stdio loop + `FastMCP`), a live Claude-Desktop connection drill, and
  a second-primitive `prompts/get` that composes a retrieval-grounded
  enrichment prompt — all `pip install mcp` + Rajat's run (§6).

### DoD
- [ ] `handle_message` dispatches initialize / tools/list / tools/call,
      returns spec-shaped JSON-RPC, `None` for notifications.
- [ ] tools/list is rendered from the registry (drift-proof test).
- [ ] tools/call routes through `execute_tool`; tool errors are
      `isError:true` content, protocol errors are JSON-RPC error codes —
      the two never confused (tested).
- [ ] No write path exists over MCP (structural test: every registry fn
      is read-only; no MCP method mutates).
- [ ] resources/list + resources/read expose the policy corpus read-only.
- [ ] auth: tools/call requires a key over HTTP; telemetry/rate-limit
      wired so an MCP client gets no unmetered side door.
- [ ] README + LAB card + 3 STUDY interview Qs per day (§3-11).

---

## 5. Failure matrix

| Failure | Behavior | Rule |
|---|---|---|
| Malformed JSON-RPC envelope | `-32600 Invalid Request`, server up | protocol degrade-not-fail |
| Unknown method | `-32601 Method not found` | — |
| `tools/call` unknown tool | tool-level `isError:true` + menu named (NOT a protocol error) | P5 unknown-tool observation, MCP-shaped |
| `tools/call` bad arguments | `isError:true` with the Pydantic validation message | typed-args gate, inherited |
| Registry fn raises | `isError:true`, class-name only, server up | P5 degrade, no stack leak |
| Notification (`initialized`) | no response returned (`None`) | JSON-RPC notification semantics |
| MCP client floods a tool | same rate-limiter/load-shedder as HTTP | no unmetered side door |
| `resources/read` unknown uri | `-32602 Invalid params` (resource not found) | — |

---

## 6. The [Claude]/[Rajat] boundary

| Item | Who |
|---|---|
| `mcp_server.py` protocol core (dispatch + 3 primitives), error taxonomy, auth/telemetry wiring, all tests | **[Claude]** |
| `pip install mcp` + the real stdio/HTTP transport shell (`FastMCP`), the Claude-Desktop `claude_desktop_config.json` entry | **[Rajat]** — the deployment leg; the core is built to drop under it |
| A live Claude-Desktop / Cursor drill actually calling our tools | **[Rajat]'s machine** (rule 3-6) |

---

## 7. Interview questions (the arc's six)

1. **"You exposed your platform over MCP — what's the blast radius of an
   untrusted MCP client?"** Answer using the inherited-guards argument:
   name the four structural guards the MCP path reuses and the one new
   surface it adds.
2. **tools/call tool-error vs JSON-RPC protocol-error:** a client sends a
   nonexistent tool name. Which error kind, why, and what breaks for the
   client's model if you return the wrong one?
3. **Why is tools/list rendered from the registry instead of a
   hand-written MCP schema?** Connect to `catalog_block()` and the P5
   "menu and whitelist cannot drift" rule.
4. **MCP has no write primitive in our server — is that a limitation or a
   design choice?** Defend it, then state exactly what you'd add (and
   what new guard each write tool would need) if a customer needed
   "ingest a policy over MCP."
5. **Local stdio can run keyless but remote HTTP cannot. Why is that not
   inconsistent?** (The transport-is-the-boundary argument.)
6. **Hand-rolled JSON-RPC core vs the `mcp` SDK's FastMCP:** what does
   building the wire format yourself prove that decorators hide, and
   what does the SDK genuinely do better that you deliberately deferred?

---

*Plan in `ROADMAP.md` §3H. The real transport + live client drill are
Rajat's (`pip install mcp`, rules 3-2/3-6). The protocol core + its
guards ship here, fully tested, no network.*
