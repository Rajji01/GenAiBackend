# P3 Design — Knowledge Assistant (chat over enrichments + policies)

> **Day-1 deliverable for P3** (before any code). Same shape as
> `P2_DESIGN.md` and the ticketing track's `WEEK*_DESIGN.md`. What
> gets built + *why the shape is what it is* + 6 interview questions
> answered separately.
>
> **P3 goal (from `Jarvis_GenAI_Path.md`):** add auth, memory, and an
> eval-as-a-system layer. In this anchor project, that means turning
> the single-shot `/enrich` API into a conversational Q&A assistant:
> "how much did I spend on food delivery last month?", "what
> subscriptions am I paying for?", answered from the enrichment
> history and policy corpus that P1 + P2 built up.

---

## Table of contents

1. [Why chat is the right shape here](#1-why-chat-is-the-right-shape-here)
2. [Data model — sessions, turns, api_keys](#2-data-model)
3. [Auth — bearer API key, hashed at rest](#3-auth)
4. [Conversation memory + token-cost cap](#4-conversation-memory--token-cost-cap)
5. [Chat prompt shape — grounded and cited](#5-chat-prompt-shape)
6. [Earned citations, again](#6-earned-citations)
7. [Eval-as-a-system](#7-eval-as-a-system)
8. [Failure matrix](#8-failure-matrix)
9. [Sequence diagrams](#9-sequence-diagrams)
10. [Endpoint contracts](#10-endpoint-contracts)
11. [Interview questions](#11-interview-questions)

---

## 1. Why chat is the right shape here

`/enrich` classifies ONE narration and returns structured data. A
real user does not naturally think in "one narration at a time" —
they think in **questions about their spend**: "what did I spend on
food this month?", "am I still paying for that subscription?", "why
was there a REFUND from Amazon on the 15th?".

Those questions all boil down to *retrieval over structured
enrichment records* — a task the existing DB + RAG stack already
does well. P3's job is to put a natural-language surface on top of
that stack:

- The user asks in prose.
- The service retrieves relevant past enrichments + relevant policy
  chunks (same rag.py that P2 already ships).
- The LLM answers in prose, but *grounded in the retrieved rows*
  and citing them explicitly (same "earned citations" rule as P2).

Non-goal: this is **not a general chatbot**. If the user asks a
question that isn't answerable from the enrichment history, the
assistant says so and stops — it does not make up transactions.

---

## 2. Data model

Three new SQLAlchemy tables added to `db.py`:

```python
class ApiKey(Base):
    __tablename__ = "api_keys"
    key_hash      : str  PK      # sha256(raw_key), never the raw key
    label         : str          # human-readable, e.g. "rajat-laptop"
    created_at    : datetime
    last_used_at  : datetime | None

class ChatSession(Base):
    __tablename__ = "chat_sessions"
    id             : str  PK     # UUID
    api_key_hash   : str  FK -> api_keys.key_hash
    created_at     : datetime
    last_active_at : datetime

class ChatTurn(Base):
    __tablename__ = "chat_turns"
    id                    : int  PK
    session_id            : str  FK -> chat_sessions.id (ON DELETE CASCADE)
    role                  : str  CHECK IN ('user', 'assistant')
    content               : str
    created_at            : datetime
    # Ground-truth retrieval snapshot for this turn — same "earned"
    # discipline as P2 policy_citations. Assistant turns only.
    retrieved_enrichment_ids   : str | None    # JSON list[int]
    retrieved_policy_chunk_ids : str | None    # JSON list[int]
```

**Why key_hash not raw key:** a leak of `api_keys.key_hash` gives an
attacker hashes to crack, not usable credentials. Same reason
passwords are hashed. The user only ever sees the raw key once, at
creation; the DB never stores it.

**Why session_id is a string UUID, not an int PK:** it's exposed in
URL paths (`/chat/{session_id}/message`). An enumerable int PK would
let an attacker guess session ids. A UUIDv4 gives ~122 bits of
unguessable state per session.

**Why CASCADE on chat_turns:** deleting a session should atomically
drop all its turns; a dangling turn without a session is a bug.
Same passive_deletes=True pattern P2 uses for PolicyChunk.

---

## 3. Auth

**Simplest thing that gives the right invariants:**

- One header: `X-API-Key: <raw>`
- Server computes `sha256(raw)` and looks it up in `api_keys`.
- If found → the row's `last_used_at` is updated, the request is
  authorized, and the resolved `key_hash` is threaded into the
  request as a dependency injection value (`Depends(require_api_key)`).
- If missing → **401** `{ "detail": "API key missing." }` (never
  echoes the header value — that could log a real key by mistake).
- If wrong → **401** with the same generic message. **Same** message
  as missing, deliberately: distinguishing "missing" vs "wrong" leaks
  timing/existence information an attacker could use to probe.

**Key creation** — a one-shot CLI utility (`create_api_key.py`),
prints the raw key to stdout ONCE, stores only the hash. Not an
endpoint: creation itself has no auth to check against, and exposing
key-creation as an HTTP route without careful bootstrapping would be
the first foothold an attacker takes. CLI-only for now; a proper
provisioning flow arrives in P7 (Secrets Manager, multi-user).

**Existing routes (`/enrich`, `/policies/*`, `/stats`) stay
un-auth-gated in P3** — backward compat with dev + P1/P2 tests. Only
the new `/chat/*` routes require the key. When multi-tenant lands
(post-P3), a config flag will opt every route into auth uniformly.

---

## 4. Conversation memory + token-cost cap

`chat_turns` is the append-only history of a session. Every user
message + every assistant message becomes a row. This is what turns
"a chat" into more than "a series of independent /enrich calls" —
turn N+1 sees turn N's context.

**But** the prompt to the LLM can't be "all past turns forever." Two
reasons:
1. Provider context window is finite (Gemini flash: 1M tokens, but
   the *cost per call* scales with token count).
2. Old turns get irrelevant fast — a question 20 turns ago about
   food delivery is noise when the current turn is about salary.

**Cap policy:** the prompt includes the **last N turns** (default
`N=6`, 3 user + 3 assistant), never more. Configurable via
`CHAT_MEMORY_MAX_TURNS`. Turns beyond N are still stored in the DB
(the history endpoint returns them for the UI), just not sent back
to the LLM.

Why not summarize old turns? Because summarization is another LLM
call per chat message — doubles the cost. If the eval later shows N=6
losing accuracy on long conversations, THEN summarization becomes
worth its cost. Not before.

---

## 5. Chat prompt shape

Three retrieval sources fold into every chat call:

```
System:
You are an assistant that answers questions about the user's bank
transactions using ONLY the retrieved records below. If the answer
isn't in the records, say so — do NOT invent transactions.

Recent transactions relevant to this question:
- id=42: "UPI/.../SWIGGY/Payment" → food_delivery, ₹450, 2026-03-14
- id=57: "UPI/.../ZOMATO/Payment" → food_delivery, ₹380, 2026-03-19
- ...  (up to top-K from enrichment_records, cosine over the
       QUESTION embedding, floor 0.65)

Applicable policy excerpts:
- [merchant_map_v3, chunk 4]: "SWIGGY, ZOMATO, DOMINOS → food_delivery"
- ...  (up to top-K from policy_chunks, same retrieve_policy_chunks
       as /enrich uses)

Conversation so far (most recent last):
- User: "how much did I spend on food last month?"
- Assistant: "..."
- User: "just the delivery apps"

Current question: "just the delivery apps"
```

**Distinct labels on purpose** — transactions are *evidence*, policy
chunks are *rules*, prior turns are *context*. Different signals; the
model treats them differently.

**The current question is at the bottom** — the model has strong
recency bias. Putting the actual question closest to where the
response is generated keeps the whole retrieved corpus subordinate
to what the user is actually asking right now.

---

## 6. Earned citations

Same rule as P2 §6, extended to chat:

- The `/chat/{id}/message` response is a `ChatReply` Pydantic:
  ```python
  class ChatReply(BaseModel):
      answer                     : str
      cited_enrichment_ids       : list[int] = Field(default_factory=list)
      cited_policy_chunk_ids     : list[int] = Field(default_factory=list)
  ```
- The LLM's structured output CAN include `cited_*` fields. **The
  service overwrites them from ground truth** — the actual retrieval
  ids that landed in the prompt for this call. The model does not
  get to invent citations to records that were never retrieved.
- The `chat_turns.retrieved_enrichment_ids` + `retrieved_policy_chunk_ids`
  columns store the same ground truth per assistant turn, so an
  audit query (`WHICH enrichments did the assistant use to answer
  turn X?`) is trivial and provably correct.

---

## 7. Eval-as-a-system

`run_eval.py` today produces a dated JSON report. That's fine for a
one-off "did I regress this week" check, but it doesn't answer:
- "How has case X's pass rate changed over the last 10 runs?"
- "Which cases have flaked more than 3 times this month?"
- "When did case Y start failing?"

**P3 adds a persistence layer under the eval:**

```python
class EvalRun(Base):
    id             : str  PK       # UUID
    started_at     : datetime
    finished_at    : datetime
    model_name     : str
    total_cases    : int
    passed         : int
    failed         : int
    notes          : str | None    # human tag: "post-P3-policy-tune", etc.

class EvalResult(Base):
    id            : int  PK
    run_id        : str  FK -> eval_runs.id (CASCADE)
    case_id       : str            # e.g. "swiggy_upi"
    passed        : bool
    expected      : str            # JSON of expected
    actual        : str            # JSON of actual
    latency_ms    : int
    error         : str | None
```

Extended `run_eval.py` writes both the JSON file (unchanged) AND
these two tables. New route `GET /eval/history?case_id=...` returns
per-case history so a "which cases regressed" query is one HTTP call,
not a manual dig through timestamped JSON files.

**Eval remains manual-run only** — auto-run per commit would burn
quota. The observability layer is what changes; the trigger doesn't.

---

## 8. Failure matrix

| Failure | Behavior | Rule enforced |
|---|---|---|
| Missing X-API-Key header on /chat/* | 401 with generic detail | Never echo the missing/wrong distinction — timing leak |
| Wrong X-API-Key value | 401 with SAME generic detail | Constant-time comparison; hash lookup by exact match |
| /chat on a session_id that doesn't exist | 404 | Distinguishes "you don't own this session" from "session id doesn't exist at all" — wait, that's an existence leak. So: 404 for both "wrong owner" and "no such session." |
| /chat on a session_id that belongs to a different api_key | 404 (not 403) | Same rule as above — hide existence from a probing attacker |
| LLM call fails during /chat | 503 + Retry-After, session left in "user asked, no assistant reply yet" state — retry safe | Same shape as /enrich's provider-error path |
| Retrieval (embed) fails during /chat | Chat still runs with degraded context (no retrieved evidence block); assistant is told "no records retrieved for this question, answer accordingly" | Degrade-not-fail — same rule as P2 |
| Memory cap N exceeded | Older turns silently trimmed from prompt; still in DB, still in /chat/{id} response | Cap is a token-cost thing, not a data-retention thing |
| DELETE /chat/{id} on missing session | 204 (idempotent) | Same rule as DELETE /policies/{id} |
| Concurrent /chat calls in same session | Serialized by DB row locking on chat_sessions.last_active_at | Prevents interleaved assistant replies confusing memory |

---

## 9. Sequence diagrams

### 9a. `POST /chat/{session_id}/message` — happy path

```
Client ──► POST /chat/<uuid>/message
             X-API-Key: <raw>
             { "message": "how much on food last month?" }
             │
             ▼
        [require_api_key] — sha256 + lookup — reject 401 or resolve key_hash
             │
             ▼
        [require_session_owner(session_id, key_hash)] — 404 if not found
             │
             ▼
        embed(message, RETRIEVAL_QUERY)   ← ONE embed call, three uses
             │
             ├──► cosine over enrichment_records  (evidence)
             ├──► cosine over policy_chunks       (rules)
             └──► fetch last N chat_turns         (context)
                                │
                                ▼
                        build_chat_prompt(question, evidence, rules, history)
                                │
                                ▼
                        [Instructor + Gemini, ChatReply]
                                │
                                ▼
                        overwrite cited_* from ground truth (earned)
                                │
                                ▼
                        BEGIN TX
                          ├─ insert user turn
                          ├─ insert assistant turn (with retrieved_* JSON)
                          └─ update chat_sessions.last_active_at
                        COMMIT
                                │
                                ▼
                        200 { answer, cited_enrichment_ids, cited_policy_chunk_ids }
```

### 9b. `POST /chat/session` — creating a session

```
Client ──► POST /chat/session   X-API-Key: <raw>
             │
             ▼
        [require_api_key] — resolves key_hash
             │
             ▼
        create ChatSession(id=uuid(), api_key_hash=key_hash)
             │
             ▼
        201 { "session_id": "<uuid>", "created_at": "..." }
```

### 9c. Degrade — retrieval fails but chat still runs

```
embed() raises
    │
    ├─► past_context   = None
    ├─► policy_context = None
    └─► prompt tells the model "no records were retrieved for this question"
                    │
                    ▼
              LLM answers based on prior conversation ONLY (or refuses)
                    │
                    ▼
              200 with empty cited_* lists — no hallucinated citations
```

---

## 10. Endpoint contracts

### `POST /chat/session`

**Request:** empty body (auth carries the identity).

**Response — 201 Created:**
```json
{ "session_id": "0e1e...-uuid-...", "created_at": "2026-09-20T..." }
```

### `POST /chat/{session_id}/message`

**Request:**
```json
{ "message": "how much did I spend on food delivery last month?" }
```

**Response — 200 OK:**
```json
{
  "answer": "You spent ₹1,230 on food delivery in March: ₹450 on Swiggy (2026-03-14), ₹380 on Zomato (2026-03-19), ₹400 on Dominos (2026-03-25).",
  "cited_enrichment_ids": [42, 57, 68],
  "cited_policy_chunk_ids": [4]
}
```

**Response — 401** on missing/wrong API key.
**Response — 404** on missing or foreign session_id.
**Response — 503** on LLM outage (same shape as `/enrich`).

### `GET /chat/{session_id}`

Returns the whole session as `{session_id, created_at, turns: [...]}`.
401/404 as above.

### `DELETE /chat/{session_id}`

204 idempotent. Cascades to `chat_turns`.

### `GET /eval/history`

Optional query params `case_id` + `limit`. Returns an array of per-run
per-case rows (or per-case rollups when `case_id` is set). No auth
gate in P3 (dev-only visibility); a real deployment would gate this.

---

## 11. Interview questions

Answer in prose separately. Six deliberately small ones — each
targets a specific decision in the design.

1. **Why `api_keys.key_hash` and not the raw key?** State the leak
   scenario each choice invites. Then: why sha256 alone here rather
   than bcrypt/argon2 (or should it be one of those)? What's the
   threat model difference between "protecting a password" and
   "protecting an API key"?

2. **The design says wrong-key and missing-key return the same 401
   detail message. Why?** Give one concrete probe an attacker could
   run if the responses differed, and one small thing on the server
   side (aside from the message) that could still leak the
   distinction if you're not careful.

3. **`chat_sessions.id` is a UUIDv4, not an autoincrement int. What's
   the specific attack this prevents,** and — for a bonus — what
   attack does UUIDv4 *not* prevent that an authenticated-owner check
   still needs to defend against on `POST /chat/{id}/message`?

4. **Memory cap N=6 turns. Read the design's argument for why we
   don't summarize older turns instead of truncating.** Argue the
   opposite side (why summarization *could* be worth it), and name
   two conditions under which you'd flip the decision. Bonus: for a
   fixed budget, how would you A/B-test truncate vs summarize?

5. **The chat call reuses the exact same
   `rag.retrieve_policy_chunks` P2's `/enrich` uses.** Trace what
   happens in the cold-start case: brand new database, no enrichments
   in `enrichment_records`, no chunks in `policy_chunks`, first
   `/chat` message ever. Walk through what the prompt looks like and
   what the assistant should honestly return.

6. **`eval_runs` + `eval_results` add persistence to a
   previously-JSON-file-only pipeline.** What one query becomes
   trivial with the tables that wasn't with just JSON files? And —
   the interviewer's real question — why is the eval trigger STILL
   manual after adding this? What quota / signal-clarity argument
   defends "we didn't wire it into CI"?

---

*Design paper, not a plan. The plan lives in `ROADMAP.md` §3B.
Update this file only if a design decision genuinely changes during
implementation — a change that would affect an interview answer.*
