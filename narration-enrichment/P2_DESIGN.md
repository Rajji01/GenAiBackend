# P2 Design — Transaction + policy RAG

> **Day-1 deliverable for P2** (before any code). Same shape as
> `ticketing-platform/WEEK2_DESIGN.md` / `WEEK3_DESIGN.md`: a design
> paper that explains what will be built, *why the shape is what it is*,
> and 6 interview questions to be answered in prose separately.
>
> **P2 goal (from `Jarvis_GenAI_Path.md`):** move from *self-retrieval*
> (past narrations, already shipped in P1 Week 3) to *document
> retrieval* — the `/enrich` prompt now sees relevant excerpts from a
> corpus of policy / rulebook / merchant-mapping docs. First genuine
> RAG-over-documents build; first AWS touchpoint on this track (S3 for
> the raw documents).

---

## Table of contents

1. [What "a policy doc" actually means here](#1-what-a-policy-doc-actually-means-here)
2. [Data model — chunks + citations](#2-data-model--chunks--citations)
3. [Chunking strategy](#3-chunking-strategy)
4. [Storage split — S3 for raw, SQLite for chunks + vectors](#4-storage-split)
5. [Retrieval + prompt weaving](#5-retrieval--prompt-weaving)
6. [Citations — earned, not decorative](#6-citations)
7. [Failure matrix](#7-failure-matrix)
8. [Sequence diagrams](#8-sequence-diagrams)
9. [Endpoint contracts](#9-endpoint-contracts)
10. [Interview questions](#10-interview-questions)

---

## 1. What "a policy doc" actually means here

Concrete examples, not "documents in general":

- A **merchant-to-category rulebook**: "narrations containing `SWIGGY`,
  `ZOMATO`, `EATCLUB` are `food_delivery`." Human-maintained. A finance
  team would keep exactly this file.
- A **subscription heuristics doc**: "if a merchant appears on the same
  amount in the same holder's history for ≥ 3 months, mark
  `is_subscription: true`."
- A **transfer/refund disambiguation policy**: "any `REFUND`,
  `REVERSAL`, or `CHARGEBACK` prefix overrides all other classification."
- A **regulatory constraint doc**: "narrations flagged as gambling
  merchants must include the merchant category `restricted`."

Common shape: short markdown/text files, 200–2000 words, edited by
humans. Not "the internet." **Trusted corpus** — the RAG's job is to
surface the *relevant excerpt*, not to filter for authority. Anything
that lands in S3 under `policy-docs/` is by definition trusted.

Non-goals: no arbitrary PDF-parsing rabbit hole in P2. Support plain
text + markdown first; PDF only if a real policy doc requires it.

---

## 2. Data model — chunks + citations

Two new SQLAlchemy tables extending the existing `db.py`:

```python
class PolicyDoc(Base):
    __tablename__ = "policy_docs"
    doc_id       : str      # user-chosen stable id, e.g. "merchant_map_v3"
    source_uri   : str      # s3://.../policy-docs/merchant_map_v3.md
    title        : str
    ingested_at  : datetime
    checksum     : str      # sha256 of the raw doc — dedup + change detection

class PolicyChunk(Base):
    __tablename__ = "policy_chunks"
    id           : int PK
    doc_id       : FK -> PolicyDoc
    chunk_index  : int      # position in the source, 0-based
    content      : str      # the actual chunk text
    embedding    : LargeBinary  # 256-dim float32, same format rag.py already uses
    embedded_at  : datetime
    __table_args__ = (UniqueConstraint("doc_id", "chunk_index"),)
```

**One `Citation` Pydantic model added to `models.py`:**

```python
class Citation(BaseModel):
    doc_id           : str
    chunk_index      : int
    snippet          : str = Field(..., max_length=280)  # ≤ tweet, not the full chunk
    similarity_score : float = Field(..., ge=0.0, le=1.0)
```

**`TransactionEnrichment` gains one field:**

```python
policy_citations: list[Citation] = Field(default_factory=list)
```

**Why `default_factory=list` and not `= []`:** Pydantic's own trap —
mutable defaults are shared across instances if not wrapped in a
factory. Same reason as Python function default arguments.

---

## 3. Chunking strategy

**Pick + defend, don't survey.** Two candidates:

| Strategy | How it works | Pros | Cons |
|---|---|---|---|
| **Fixed-size + overlap** | e.g. 500 chars per chunk, 50 char overlap | Boring, deterministic, easy to test as a pure function | Can split a sentence mid-word |
| **Semantic** | Split on paragraphs, then merge until ≤ target size | Never splits mid-sentence | More code, more edge cases, needs a splitter dep |

**Decision: fixed-size + overlap first.** Same "avoid overengineering"
rule that kept P1 on SQLite instead of a vector DB. If the eval golden
dataset shows the fixed chunker losing accuracy vs semantic, upgrade
then, with the numbers to justify it. Not before.

**Parameters (proposal, review during Day 2):**
- `chunk_size = 500` chars — small enough to fit ~10 chunks in the
  prompt without blowing the context budget, large enough to keep a
  policy rule intact in one chunk.
- `overlap = 50` chars — a rule that straddles two chunks stays
  retrievable via either.
- `chunk()` is a **pure function** — no I/O, no DB. Trivially unit-testable
  with `assert chunk("abcdef", 3, 1) == ["abc", "cde", "ef"]`.

---

## 4. Storage split

Deliberate two-tier split, mirroring P1's Postgres/Redis split in
spirit:

| Store | Holds | Why |
|---|---|---|
| **S3** | Raw policy docs (the source of truth text) | Durable, addressable, cheap. First AWS touch on this track. |
| **SQLite** | `policy_docs` (metadata) + `policy_chunks` (chunks + embeddings) | Fast retrieval path stays local — no S3 round-trip on every `/enrich`. |

**Rebuild rule:** a chunk table can always be rebuilt from S3 by
re-running the ingest for every `doc_id`. Chunks + embeddings are a
**cache**, not the source of truth. This is what makes S3 durable
storage worth its while — losing SQLite is annoying, not catastrophic.

**AWS boundary — user-driven per standing rule §3-2.** Claude pairs on
`boto3` + config, user creates the S3 bucket in the AWS console.
Tests use `moto` (mock-S3), no real credentials in CI.

**`.env` additions (mockable):**
```
POLICY_S3_BUCKET=jarvis-narration-policies-dev
POLICY_S3_PREFIX=policy-docs/
AWS_REGION=ap-south-1     # user-picked in step 1 of P2 Day 4
```

---

## 5. Retrieval + prompt weaving

**Existing (P1 Week 3):** `rag.py` embeds the incoming narration, cosine-
searches `enrichment_records` for past classifications, folds top-3 into
prompt as "here's how similar past narrations were classified."

**P2 extends this in parallel — NOT in serial:**

```
narration
   │
   ├──► embed as RETRIEVAL_QUERY
   │       │
   │       ├──► cosine-search enrichment_records  (past classifications)
   │       └──► cosine-search policy_chunks       (applicable policy)
   │
   └──► prompt gets two clearly-labeled blocks:
        [SIMILAR PAST CLASSIFICATIONS]     top-3, floor 0.70
        [APPLICABLE POLICY EXCERPTS]       top-3, floor 0.65

Policy floor is slightly lower than past-narrations floor because
policy chunks are shorter and more abstract — they'll score lower on
average even when highly relevant.
```

**One embedding call, two searches** — the narration is embedded *once*
(as a query) and used against both tables. This matters because embedding
calls are the slowest step in `/enrich`.

**Prompt structure (concrete):**

```
System:
You classify bank narrations. Return TransactionEnrichment.

Similar past classifications (may or may not apply):
- "UPI/P2M/.../SWIGGY/Payment"  → category=food_delivery, confidence=0.95
- ...

Applicable policy excerpts (from trusted policy docs):
- [merchant_map_v3, chunk 4]: "narrations containing SWIGGY, ZOMATO,
  EATCLUB are food_delivery."
- ...

Narration to classify:
"..."
```

**The two blocks are visually distinct in the prompt** — the model
should treat past classifications as *evidence* and policy as *rules*.
Prompt-engineering-wise these are different signals.

---

## 6. Citations

**The contract:** `policy_citations` in the response may only reference
chunks that *actually appeared in the prompt for this call*. Never a
chunk that scored high but was dropped by the top-3 cutoff. Never a
chunk from a different doc than what was retrieved.

**How enforced (in code, not just in docs):**

```python
def enrich_and_persist(narration):
    past = retrieve_past_narrations(narration)
    policy_chunks = retrieve_policy_chunks(narration)  # up to top-3

    prompt = build_prompt(narration, past, policy_chunks)
    enrichment = llm_call(prompt)  # returns TransactionEnrichment

    # THE ASSERTION — earned, not decorative:
    enrichment.policy_citations = [
        Citation(
            doc_id=c.doc_id,
            chunk_index=c.chunk_index,
            snippet=c.content[:280],
            similarity_score=c.score,
        )
        for c in policy_chunks   # ONLY the chunks that made it into the prompt
    ]
    return enrichment
```

Even if the LLM output includes a `policy_citations` field of its own
(from Instructor's function-calling), we overwrite it with the ground
truth from our own retrieval. **The model doesn't get to choose what to
cite.** It only gets to choose what to *classify*.

**Why this matters:** citation hallucination is one of the most-quoted
RAG failure modes in interviews. Fixing it in architecture (not by
"asking the model nicely to cite accurately") is a differentiator.

---

## 7. Failure matrix

| Failure | Behavior | Rule enforced |
|---|---|---|
| S3 unreachable at ingest time | `POST /policies/ingest` returns 503 with `Retry-After` | Ingest is a control-plane op; failing loudly is right |
| S3 unreachable at retrieval time | Never happens — retrieval doesn't hit S3, only the local `policy_chunks` table | Storage split earns its keep here |
| Embedding call fails at ingest | Ingest fails; no half-embedded doc persisted (transaction rolls back) | Chunks-without-vectors would silently degrade retrieval quality later |
| Embedding call fails at query time | `retrieve_policy_chunks` returns `[]`, `/enrich` proceeds without policy context, logs a warning | Same rule as P1 Week 3: RAG degrades, never fails, the request |
| Empty `policy_chunks` table (no docs ingested yet) | `retrieve_policy_chunks` returns `[]`, prompt gets no policy block | First calls work exactly like pre-P2 |
| Chunk contradicts a past narration | Model sees both in the prompt with distinct labels; policy is a *rule*, past is *evidence* — expected outcome is policy wins | Verified with an eval case that exercises exactly this |
| Same doc_id re-ingested | Old chunks deleted, new chunks inserted, all in one transaction | Idempotent ingest is a control-plane invariant |
| Doc uploaded, checksum unchanged | Ingest returns 200 with `unchanged=true`, no work done | Costs no embedding budget on no-op |

---

## 8. Sequence diagrams

### 8a. `POST /policies/ingest` — happy path

```
Client ──► /policies/ingest (multipart or {source_uri})
             │
             ▼
        FastAPI validates
             │
             ▼
        [PolicyIngestService]
             │  read raw doc bytes
             ▼
             ├─────────────► S3.put_object(doc_id → bucket)
             │
             ▼
        chunk(text) — pure function
             │
             ▼
        embed_batch(chunks) — one API call, N chunks
             │
             ▼
        BEGIN TX
             ├─ delete existing chunks for doc_id (if any)
             ├─ insert PolicyDoc row (with checksum)
             └─ insert N PolicyChunk rows
        COMMIT
             │
             ▼
        200 {doc_id, chunks_ingested, unchanged: false}
```

### 8b. `POST /enrich` with P2 changes

```
Client ──► /enrich {narration}
             │
             ▼
        [RateLimiter.acquire] — reject fast on 429
             │
             ▼
        embed(narration, RETRIEVAL_QUERY)  ← ONE call
             │
             ├──► cosine-search enrichment_records  (past, top 3, floor 0.70)
             └──► cosine-search policy_chunks       (policy, top 3, floor 0.65)
                                │
                                ▼
                        build_prompt(narration, past, policy)
                                │
                                ▼
                        [Instructor call, Mode.TOOLS]
                                │
                                ▼
                        TransactionEnrichment
                                │
                                ▼
                        overwrite policy_citations from ground truth
                                │
                                ▼
                        persist to enrichment_records (P2: with vector, unchanged)
                                │
                                ▼
                        200 {..., policy_citations: [...]}
```

### 8c. Degrade paths

```
Embedding fails during retrieval:
    log warning + correlation_id
    past = []
    policy = []
    prompt has neither block
    /enrich still returns 200

S3 fails during ingest:
    503 Retry-After
    no partial state written to SQLite

Empty policy corpus:
    retrieve_policy_chunks returns []
    /enrich prompt omits the policy block entirely
    behavior === P1 Week 3
```

---

## 9. Endpoint contracts

### `POST /policies/ingest`

**Request:**
```json
{
  "doc_id": "merchant_map_v3",
  "title": "Merchant → category mapping (v3)",
  "content": "...raw markdown or plain text..."
}
```
*(Or multipart form with a file field; both accepted.)*

**Response — 200 OK:**
```json
{
  "doc_id": "merchant_map_v3",
  "source_uri": "s3://jarvis-narration-policies-dev/policy-docs/merchant_map_v3.md",
  "chunks_ingested": 8,
  "unchanged": false,
  "checksum": "sha256:..."
}
```

**Response — 200 OK, no-op:**
```json
{ "doc_id": "merchant_map_v3", "unchanged": true, ... }
```

**Response — 503 with `Retry-After`** when S3 is unreachable.

### `GET /policies` — list ingested docs

```json
[
  {"doc_id":"merchant_map_v3","title":"...","chunk_count":8,"ingested_at":"..."},
  ...
]
```

### `DELETE /policies/{doc_id}` — remove doc + all its chunks

Idempotent. Returns 204 either way.

### `POST /enrich` — unchanged shape, response gains `policy_citations`

```json
{
  "merchant": "Swiggy",
  "category": "food_delivery",
  "confidence": 0.95,
  "policy_citations": [
    {
      "doc_id": "merchant_map_v3",
      "chunk_index": 4,
      "snippet": "narrations containing SWIGGY, ZOMATO...",
      "similarity_score": 0.83
    }
  ]
}
```

---

## 10. Interview questions

Answer these in prose separately (either in this file's §10.answers
appendix Rajat maintains, or on paper). No answers by design — writing
the answer is the point.

1. **Why is the chunking function a pure function, and what would break
   if it read the S3 doc directly instead of taking `text: str` as a
   parameter?** Think about testability + the ingest transaction
   boundary.

2. **Why do we overwrite `policy_citations` from ground truth even
   though Instructor's function-calling gives us a citations field in
   the model output "for free"?** What's the failure mode this
   overwrite defeats, and what would happen without it in a live demo?

3. **The past-narration floor is 0.70; the policy floor is 0.65. Why is
   the policy floor lower, and why might that decision need to change
   after the eval golden dataset gets extended?**

4. **When the embedding call fails at retrieval time, `/enrich` returns
   200 with an empty policy block. When it fails at ingest time,
   `/policies/ingest` returns 503. Why the asymmetry?** Think about
   read paths vs write paths.

5. **The raw doc goes to S3, but the chunks + vectors go to SQLite. If
   both storage systems were free, would you still split them this way?
   What's the actual engineering benefit of the split, and what breaks
   if we colocated both in SQLite instead?**

6. **Same `doc_id` re-ingested with unchanged content should be a no-op.
   Same `doc_id` re-ingested with *changed* content replaces the chunk
   set atomically. Why does the atomicity matter for the `/enrich` read
   path?** Think about a concurrent `/enrich` firing mid-re-ingest.

---

*Design paper, not a plan. The plan lives in `ROADMAP.md` §3. Update
this file only if a design decision genuinely changes during
implementation — a change that would affect an interview answer.*
