# AGENTS.md — Bootstrap for AI assistants

**If you're a Claude/Codex/other AI session opening this repo fresh — start here.** This file exists so a new session on any machine (or a fresh clone) can orient itself in 2 minutes and pick up work correctly. Machine-local memory (in `~/.claude/...`) is not portable; this file is.

> **Rule zero:** read this file, then the pointed-to docs in **§8 Key files**, before writing any code or making any commit.
>
> **Companion:** `FILE_GUIDE.md` (repo root) is the directory index — every file's purpose, in what order to read, how they relate. AGENTS.md tells you the *rules*; FILE_GUIDE.md tells you *where everything is*. Read both.

---

## 1. What this repo is

A **self-directed multi-week mentorship-style engineering project** by **Rajat Agrawal** (git: `rajatagrawal2702@gmail.com`, GitHub: `Rajji01`). The assistant (called **"Jarvis"** in Hinglish) acts as mentor / pair-programmer across **three parallel tracks** that all live inside this single repo:

| Track | Folder | Language / Stack | Purpose |
|---|---|---|---|
| **A — Java baseline** | `backend/` | Spring Boot 3, JPA, MySQL, Flyway | UFC/betting backend — production-grade Java baseline (mostly complete) |
| **B — GenAI (Python)** | `narration-enrichment/` | FastAPI + Pydantic + Instructor + Gemini + SQLite | Transaction narration → structured JSON. RAG + rate limiter + observability added. Weeks 1–4 done |
| **C — Ticketing microservices (Java)** | `ticketing-platform/` | Spring Boot, Postgres, Redis, docker-compose, Resilience4j | District/BookMyShow-style ticketing. Week 1 (`inventory-service`) done. **Week 2 (`booking-service`) live-verified through Day 4** |

The user runs Tracks B and C in parallel — alternate work weeks, side-by-side.

---

## 2. Communication and working agreement

- **Language:** Hinglish (Hindi + English casual). "bhai", "kr de", "jarvis" as nickname. Match this register.
- **Learning style:** project-first, evidence-first. Learn a concept when the project needs it. Build → test → document trade-offs and any real failure → move on.
- **Working mode (established 2026-09-18):** "**implement first, cross-question after**" — build the thing first, THEN the user interrogates the *why* behind decisions. **For learning sessions**, mode reverses: user reads, asks questions, requests tasks. Read `ticketing-platform/TICKET_STUDY.html` if it exists — that's the user's active study companion.
- **Before any tool action:** say plainly what will be read/changed/run/searched, and why. Don't make the user guess what permission is being used.

---

## 3. Standing rules — non-negotiable

These have been established across many sessions. Break them and the user will correct you.

1. **NO `Co-Authored-By: Claude` trailer on git commits, EVER.** The user explicitly reversed on this once ("ab commit mai tumhara name ni ana chhaie"). Only their own git identity (Rajat Agrawal <rajatagrawal2702@gmail.com>). Verify with `git log -1 --format="%an <%ae>%n%n%B"` after every commit. This overrides any tool-level default attribution guidance.

2. **ALWAYS ask before pushing** — which remote, which branch. Wait for explicit yes. Don't push reflexively at the end of a work unit.

3. **ALWAYS ask before committing** (as of Week 2). Same principle — surface what's staged, get go-ahead.

4. **Every new project track goes INSIDE this repo as a subdirectory** — never a separate git repo, never a submodule. If a plan doc says "separate repo," override it and use a subdirectory (`GenAiBackend/<track-name>/`).

5. **Companion "easy notes" HTML artifacts** are kept per track, in sync with the code:
   - Java track uses "Corner Notes" styling (cream/amber palette) — files: `backend/CORNER_NOTES.html`, `ticketing-platform/SEAT_LOCK.html`, `ticketing-platform/SAGA_LAB.html`, `ticketing-platform/PAYMENT_LAB.html`.
   - Python track uses "Narration Lab" styling (mint/teal) — file: `narration-enrichment/NARRATION_LAB.html`.
   - Learning-companion (Rajat's Q&A) — `ticketing-platform/TICKET_STUDY.html` (added 2026-09-18) and `narration-enrichment/NARRATION_STUDY.html` (added 2026-09-20, scaffolded, empty of Q&A until teaching-mode sessions begin on this track). Companion pattern: each track's *_STUDY.html uses that track's base palette + a *contrasting* accent for Q&A blocks (teal on Corner Notes cream for ticketing; amber on Narration Lab mint for narration) so a fresh reader can tell "explained content" from "questions asked" at a glance.
   - **One showcase HTML per Week** (confirmed 2026-09-20). Don't grow SAGA_LAB to cover Week 3; spawn PAYMENT_LAB. Rule: `<Week-N>_<theme>.html` for each week's headline focus. Prevents any one file from overloading, keeps concerns cleanly separated per week's arc.

6. **Live verification, no cherry-picking.** Real API calls, real Docker containers, real DB. When a live result is "boring" or null, report it honestly rather than swapping for a flattering example.

7. **Don't overengineer.** Explicitly avoided: vector DB where SQLite serves (P1 RAG), numpy for one cosine function. Smallest infrastructure that satisfies the current requirement. Flag deliberate compromises in comments/docs.

8. **JUnit strategy (Week 2 update, reconfirmed Week 3):** For learning-first sessions, **defer JUnit-writing to end-of-week clean pass**. Implement + mentally verify + document reasoning first; write proper tests over the finished shape. Manual/live verification is fine and encouraged where feasible.

9. **Track continuously; never leave state stale (added 2026-09-20).** After every meaningful chunk of work, update: (a) local memory (`~/.claude/projects/.../memory/`), (b) `AGENTS.md` §4/§5 if state changed, (c) `FILE_GUIDE.md` if a new file class was added, (d) track README (build log). Rule: every user-facing directive I'm told to follow ("do X from now on", "don't do Y again", "the pattern is Z") gets captured in this file's §3 or the appropriate memory. Future sessions must not have to re-learn what this one already learned.

10. **Schema evolution = Flyway, never Hibernate `ddl-auto: update` (added 2026-09-20 hardening).** Every service in `ticketing-platform/` uses `spring.jpa.hibernate.ddl-auto: validate` + Flyway migrations in `src/main/resources/db/migration/`. Bug 4 (Postgres init-script skipped on populated volume) and Bug 7 (Hibernate silently skipped adding a NOT-NULL column without DEFAULT on a populated table) are both permanently defused by this. `baseline-on-migrate: true` + `baseline-version: 0` lets Flyway adopt already-populated volumes (V1 skipped as baseline) while running V1 normally on fresh volumes — same terminal schema either way. **Add a new migration as `V<N+1>__<snake_desc>.sql` — never edit V1 after it's shipped.** Spring Boot 3 needs `flyway-database-postgresql` as a separate dep alongside `flyway-core`.

11. **Per-day easy-notes + interview-Q blocks (added 2026-09-20).** Every implemented "Day N" of a Week (ticketing) or "P#·Day N" of a Project (narration) MUST ship, alongside the code commit, two artifacts:
    - **Easy-notes card** in that track's showcase HTML (`<Week-N>_<theme>.html` / `NARRATION_LAB.html`) — descriptive, eye-catching, mini-cards format: WHAT the day built + WHY + one gotcha + test count. Written so Rajat re-reads at revision time and understands the code without opening the source.
    - **3 interview Qs** in that track's `*_STUDY.html` — 2 easy (Python/Java basics or trace-this-code) + 1 conceptual (practical + theory + hands-on, the interview-signature one). Each Q anchors to a real file/function/commit in *this* project so reading the Q, jumping to the code, then answering is the intended loop. Kept small — a single Q is not a whole topic. Stored in a "Daily interview questions" section per project/week.
    - Purpose: implement + revise + interview-prep from one commit, no separate write-up pass. If a day's code lands without both, the day isn't done.

---

## 4. Current state (as of 2026-09-18)

### Ticketing (Track C) — WHERE MOST OF THE ACTION IS

- **Week 1** — inventory-service ✅ **DONE + committed + pushed** (`0b97be5`).
- **Week 2** — booking-service ✅ **DONE + committed + pushed** (`1abd8ec` code, `b9e507e` notes). 6 live-verified failure experiments, 3 real bugs caught+fixed live.
- **Week 3 (DONE 2026-09-20)** — payment-service + outbox pattern + refund path + dangling-saga recovery + notification-service downstream consumer + MDC-across-scheduled-boundary fix. Commits: `e4cb1d8` Day 1 design, `2e767a4` Day 2 payment-service, `2629131` Day 3 booking-side (PaymentClient + Outbox + Recovery), `d1ddd5e` Day 4 live-verify + docs, `8235fea` Day 5 notification-service (outbox end-to-end), `8a30afa` Day 6 correlation-id fix, `0f57290` + `a9233dd` Day 7 consumer dedup by event_id. Live-verified with 7 checks + F1/F2 failure experiments + 4-service end-to-end pipeline.
- **Post-Week-3 hardening (2026-09-20)** — Flyway migrations added across all 4 services (payment, inventory, booking, notification). `ddl-auto` flipped from `update` → `validate`; each service now has `V1__initial_<x>_schema.sql`. Bug 4/7 permanently defused. See standing rule §3-10.

- **Week 4 (up next)** — AWS foundation per ROADMAP (IAM/VPC/RDS/ECR/ECS Fargate/ALB). **User-driven per standing rule.** Claude pairs on Terraform + verification but does NOT autonomously touch AWS resource creation ("bs aws ki service smai banaunga" — 2026-09-20 reconfirmation).
  - New module `payment-service/` — Java 17 Spring Boot, Adapter+Factory+Strategy for UPI/Card/NetBanking stubs, 6-state Payment machine, 2-step auth+capture. Own Postgres DB (`payment`).
  - booking-service updates: `PaymentClient` (Resilience4j with fresh `payment` instance, all Bug 5+6 lessons pre-applied), Outbox (entity + repo + service + poller + `EventBus` stub), `BookingRecoveryService` (2-min age filter, drives forward or rolls back), refund path on captured-but-confirm-fail, `Booking.payment_id` + `refund_pending` columns.
  - docker-compose: payment-service added on 8083, `create-payment-db.sh` init script.
  - `WEEK3_DESIGN.md` full design paper + 7 more interview Qs.

**Uncommitted since last push (`8d255fe`)**:
- Week 3 additions above (~45 new/modified files across payment-service, booking-service, ticketing-platform root)
- `AGENTS.md` §5 flip to implementation-mode (this file)
- `README.md` (ticketing) Week 3 build log entry

User instruction 2026-09-20: **do not commit, keep implementing to 2M token budget.** Also: no junit tests (manual verify where feasible).

**Pending for Week 3 completion:**
- Live-verify against a running 3-service stack (Day 4 equivalent)
- Update SAGA_LAB.html (or new PAYMENT_LAB.html?) with Week 3 concepts + bug museum entries if live finds any
- User answers 7 more interview questions in `WEEK3_DESIGN.md §9`
- Eventual commit + push (needs user OK)

### Narration (Track B) — P1 done, P2 up next

**Status:** P1 (Transaction Enrichment API) ✅ **DONE + committed + pushed** through last narration commit `20cb3c6` (Week 4 `/stats`). 68 tests green, no network in the suite.

**P1 shipped across four "weeks" (phases):**
- **Week 1** — base `POST /enrich`: Instructor + Pydantic + Gemini + FastAPI + Dockerfile + docker-compose with healthcheck. Commit `4cb3d86`.
- **Week 2** — evaluation (`eval/run_eval.py` + 12-example golden dataset, discovered 5rpm/20rpd live), batch + persistence (`db.py`, SQLite `StaticPool` fix), retry-with-backoff via `tenacity` (only 429/503/504). Commit `7b92cbe`.
- **Week 3** — a real live-caught bug (`InstructorRetryException` wraps every failure, exhausted 503 reported as misleading 422; fix inspects `exc.__cause__`) commit `516ccce`. Then RAG for consistency (`rag.py`, `gemini-embedding-001` 256-dim, cosine over own persisted enrichments, `task_type` asymmetry, live-proved via UBER case) commit `8fea40d`.
- **Week 4** — sliding-window rate limiter (`rate_limiter.py`) commit `4899753`. Correlation IDs via `contextvars.ContextVar` + a live-caught `Logger.addFilter` vs `Handler.addFilter` bug commit `3f8985d`. `/stats` endpoint (DB aggregation + non-mutating rate-limiter peek, `null` not fake-`0.0` on empty table) commit `20cb3c6`.

**P2 (Transaction + policy RAG) — DONE 2026-09-20** through Day 6. Shipped in six day-specific commits:
- Day 1: bootstrap layer (ROADMAP + P2_DESIGN + NARRATION_STUDY scaffold) — commit `f6b504b`.
- Day 2: chunker (pure function) + PolicyDoc/PolicyChunk models + Citation schema — commit `6fedd43`.
- Day 3: `POST /policies/ingest` idempotent-by-checksum + GET /policies + DELETE — commit `b72db22`.
- Day 4: S3 backing for raw docs (boto3 + moto, bucket creation deferred to Rajat per rule 3-2) — commit `b5906ae`.
- Day 5: policy retrieval + prompt weaving + **earned-not-decorated citations** (LLM-invented citations get overwritten from ground truth in `_enrich_and_persist` — regression test `test_llm_provided_citations_are_overwritten_not_appended` proves the LLM can never smuggle a hallucinated citation past the code) — commit `2d9a5fc`.
- Day 6: eval extension (5 policy-driven cases + `eval/policy_seeds.json`) + README first-class "Policy RAG (P2)" section + LAB wrap-up banner. Live end-to-end proof deferred to a Rajat-driven run since it burns Gemini quota; mocked contract test covers the code-side invariant in the meantime.
- 128 tests green, up from 68 at P1 close. Zero regressions.
- Along the way: rule 3-11 added ("every day ships easy-notes card in LAB + 3 interview Qs in STUDY alongside the code commit"), 18 interview Qs authored across Days 2-6 in NARRATION_STUDY.html.

**P3 (Knowledge assistant) — DONE 2026-09-20** through Day 6. Shipped in six day-specific commits:
- Day 1: P3_DESIGN.md + ROADMAP §3B (11-section design paper + 6 interview Qs) — commit `0d200b8`.
- Day 2: API-key auth (X-API-Key bearer, sha256 hashed at rest, hmac.compare_digest, missing/wrong both 401 same body, CLI-only key creation) — commit `5fbe346`.
- Day 3: chat_sessions + chat_turns tables (UUIDv4 session ids, FK CASCADE, role CHECK constraint) + four auth-gated /chat routes with a `[stub-echo]` LLM stub proving plumbing before Day 4's swap — commit `732198d`.
- Day 4: real LLM chat via new `chat_service.py` — memory cap N=6, retrieval-grounded prompt (one embed → two searches), **earned citations overwrite in code** (regression test `test_llm_provided_citations_get_overwritten_from_ground_truth` proves the LLM cannot smuggle a hallucinated id past the service) — commit `d7a8e81`.
- Day 5: eval-as-a-system — eval_runs + eval_results tables, `run_eval.py` persistence non-fatal, `GET /eval/history` two-mode (rollup / per-case details) — commit `7eed5d7`.
- Day 6: closeout — README first-class "Knowledge assistant (P3)" section, NARRATION_LAB "P3 shipped" banner + Day-6 card documenting the four invariants P3 leaves for P4, 18 daily interview Qs total on P3 in NARRATION_STUDY, ROADMAP DoD flipped, this AGENTS.md synced, local memory synced.
- **168 tests green** (was 128 at P2 close). 45 new tests across Days 2–5 (auth timing-safety, session ownership, existence-hiding, earned citations, memory-cap, retrieval degrade path, eval persistence + query). Zero P1/P2 regressions.
- Rule 3-11 (per-day easy-notes card + 3 interview Qs) held across every P3 code day.

**Four invariants P3 leaves on the codebase for P4 to inherit:**
1. **Auth-first is the default posture.** Any new user-facing route gets `Depends(auth.require_api_key)` from the moment it exists.
2. **Existence-hiding on 404 is uniform.** "Not there" and "not yours" return the same body across `/policies/{id}` and `/chat/{id}`.
3. **Earned citations enforced in code.** `/enrich.policy_citations` (P2 D5) and `/chat.cited_*` (P3 D4) both overwrite from ground truth. Regression-tested on both surfaces.
4. **Observability persisted alongside expensive ops.** P3 D5's eval_runs pattern; P4 will replicate for SQS queue depth + DLQ persistence.

**Next work unit — P4 (Async doc-processing pipeline).** **AWS ka asli ghar per the master plan.** First genuine microservice split: API service (queue and return) + Worker service (embedding/LLM heavy). SQS + DLQ + S3 + ECS/Lambda + CloudWatch. **AWS bucket/queue creation is Rajat's per standing rule 3-2** (reconfirmed live during P2 D4 and again during P3 D2 "isme koi api kye to ni jo hmne commit kr di ho"). Claude pairs on Terraform + boto3 + moto-based tests; user provisions real resources. See `Jarvis_GenAI_Path.md` for strategic framing; a P4-specific ROADMAP + DESIGN pass lands when Rajat greenlights P4 start. **P4 not yet started.**

**Cross-track parallels worth remembering** (these keep the two tracks reinforcing each other):
- Ticketing's `CorrelationIdFilter` (Java thread-local MDC) ↔ narration's `correlation.py` (Python `ContextVar`).
- Ticketing's Bug 5 rule (whitelist-only, no ignore-exceptions with parent classes on Resilience4j) ↔ narration's rule that retry only fires on 429/503/504 (whitelist), never on Instructor's `InstructorRetryException` blanket.
- Ticketing's outbox pattern (dual-write defeated by atomic state + outbox row) ↔ future P4 target on this track (async doc-processing pipeline uses the same shape in Python + SQS).
- Both tracks apply the "degrade-not-fail" rule to RAG/retrieval paths — a broken embedding never turns a 200 into a 500.

### Java baseline (Track A)

- Treated as largely complete. Reference architecture for other tracks (RFC 7807, correlation ID pattern, exception handler shape).

---

## 5. The teaching arc (PAUSED as of 2026-09-20 — implementation mode active)

**Current mode: implementation.** Teaching arc paused; will resume ONLY when user explicitly says "Section N chalu kr" or equivalent. Do NOT proactively teach — user is now driving implementation.

Active study companion `ticketing-platform/TICKET_STUDY.html` — captured so far:

- ✅ **Section 1** — Problem statement (Seat entity, enum, unique constraint)
- ✅ **Q1** — Enum vs String (compile-time safety, EnumType.STRING vs ORDINAL)
- ✅ **Q2** — `@Version` alone enough for concurrency? (optimistic vs pessimistic, 4 cases where not enough)
- ✅ **Section 2** — Do stores, do lifetimes (Redis no-volume as feature, 2-store coord, alternatives)
- ✅ **Q3** — Redis fast kyun/kaise? (4 sub-parts: SETNX mechanism, Postgres cache overhead, single-thread atomicity, 100-client mechanics)
- ✅ **Q4** — Context switching + cache invalidation + lock contention — easy way with 4 analogies
- ⏸️ **Section 3 (queued)** — Concurrency 2-tier defense (Redis SETNX + Postgres @Version deep). **Do NOT start until user says so.**
- 📖 Sections 4–8 remaining (compensating actions, reconciliation, confirm+afterCommit, endpoint contract, cross-cutting)
- ⏳ **S2's 3 self-check Qs** — user answers still pending. Q5 will land here when they arrive.

**Signal to resume teaching:** user says "section N chalu kr" / "start section" / "teaching mode wapas" / equivalent. Any user question about a concept without teaching signal → answer in-place, do NOT expand into a full section.

---

## 6. Roadmaps (source of truth for what to do next)

**Ticketing track:** `ticketing-platform/ROADMAP.md` — the master plan (10 phases, weeks 2 onward). This SUPERSEDES an older `codes Practice/Jarvis_Architect_Path.md` which had a different Phase 1 ordering. Follow `ROADMAP.md`.

**GenAI track:** `Jarvis_GenAI_Path.md` (this dir) — P1 → P8 projects. Currently at P1 Week 4+ done.

**Cross-track forward plan:** `NEXT_PATH.md` (this dir) — my synthesis of what's next on both tracks, with `[PLAN]` markers for what's in the roadmap files verbatim vs `[PROPOSAL]` for my forward-looking suggestions.

**Historical context (partially outdated):** `JARVIS_OPENAI_CONTEXT.md` — written by an OpenAI-based session mid-Week-4 of narration, before Week 2 ticketing started. Useful for background but current state is in the above files.

---

## 7. Environment quirks worth remembering

- **This machine (Windows 10, Docker Desktop 20.10.17):** Docker daemon is slow/fragile under load. A cold multi-service `docker compose up --build` can take 9+ minutes and may push the daemon into an unresponsive state. **Preferred pattern:** run Postgres + Redis in Docker, run Spring Boot services via `./mvnw spring-boot:run` from the host.
- **Postgres init scripts run ONLY on fresh volume.** A restart against an existing `pgdata` skips `db-init/`. If `booking` database is missing after a fresh compose, manually create via `docker exec ... psql`. (This is Bug 4 in the SAGA_LAB bug museum.)
- **Shell:** Git Bash primary. Some commands need `powershell.exe -Command` (e.g. `Start-Process chrome`).
- **User's git identity:** Rajat Agrawal <rajatagrawal2702@gmail.com>. Repo: `github.com/Rajji01/GenAiBackend`.

---

## 8. Key files — the whole map

### Bootstrap (READ FIRST in a new session)
- **`FILE_GUIDE.md`** — directory index for every file, categories, reading order, HTML design systems, discovery patterns
- `AGENTS.md` (this file) — rules, current state, teaching arc, environment quirks
- `README.md` — one-liner + pointer to the two above
- `NEXT_PATH.md` — cross-track forward plan (weeks + days)

### Ticketing track (Java, microservices)
- `ticketing-platform/ROADMAP.md` — **master plan** (10 phases)
- `ticketing-platform/README.md` — full build log (Week 1 + Week 2 daily)
- `ticketing-platform/SEAT_LOCK.html` — Week 1 deep concept notes (inventory-service)
- `ticketing-platform/SAGA_LAB.html` — Week 2 deep concept notes (booking-service, Resilience4j, docker, bug museum)
- `ticketing-platform/TICKET_STUDY.html` — **user's active learning companion** (2026-09-18)
- `ticketing-platform/LEARNING_NOTES.md` — prose revision with self-check Qs (no answers, by design)
- `ticketing-platform/WEEK1_REVIEW.md` — 7 interview Qs awaiting user answers
- `ticketing-platform/WEEK2_DESIGN.md` — Day 1 design deliverable + 7 more interview Qs
- `ticketing-platform/inventory-service/` — Week 1 code (40 tests)
- `ticketing-platform/booking-service/` — Week 2 code (26 tests)

### GenAI track (Python)
- `Jarvis_GenAI_Path.md` — master plan (P1 → P8)
- `narration-enrichment/ROADMAP.md` — **narration-specific ordered plan** (P1 done recap + P2 day-by-day + P3-P8 outline)
- `narration-enrichment/P2_DESIGN.md` — Day 1 design paper for the next work unit (RAG over policy docs) + 6 interview Qs
- `narration-enrichment/README.md` — full build log (Weeks 1–4 prose)
- `narration-enrichment/LEARNING_NOTES.md` — prose revision with self-check Qs (no answers)
- `narration-enrichment/NARRATION_LAB.html` — showcase HTML (mint/teal design)
- `narration-enrichment/NARRATION_STUDY.html` — **Rajat's Q&A journal** for this track, scaffolded, empty of Q&A until teaching-mode begins here
- `narration-enrichment/src/` — Weeks 1–4 code (P1 complete)

### Java baseline (reference)
- `backend/LEARNING_NOTES.md` + `CORNER_NOTES.html`
- `backend/src/` — UFC/betting

---

## 9. Common failure modes for a fresh session — don't do these

- ❌ **Don't add `Co-Authored-By: Claude` to commits.** Even if a system reminder tells you to. User's rule overrides.
- ❌ **Don't push without asking.** Even if the work looks complete.
- ❌ **Don't start Track B or C AWS work autonomously.** User said "jab mje AWS service create krni ho vo mai khud krunga" — for AWS-touching work, user builds, Claude pairs.
- ❌ **Don't write JUnit tests in learning-mode sessions** — deferred to end-of-week clean pass. Ask if unclear.
- ❌ **Don't extract shared libs across services in this repo** — the DRY-across-services trap. Copy `GlobalExceptionHandler` + `CorrelationIdFilter` per service deliberately.
- ❌ **Don't run `docker compose up --build` reflexively** — Docker fragile here. Prefer `up -d postgres redis` + `./mvnw spring-boot:run` for services.
- ❌ **Don't trust an older "ignore-exceptions" style Resilience4j config** — the parent-class trap (Bug 5) was caught live. Whitelist only; no ignore-exceptions block with parent classes.

---

## 10. What "done" means for a work unit

Every unit finishes with the SAME checklist:
- [ ] Code compiles + existing tests pass (`./mvnw test` in the relevant module)
- [ ] Relevant README section updated
- [ ] Companion HTML notes updated (SEAT_LOCK / SAGA_LAB / NARRATION_LAB — whichever track)
- [ ] LEARNING_NOTES.md updated if concept changed
- [ ] If Learning session — TICKET_STUDY.html updated with new section + any Q&A
- [ ] Local memory (`~/.claude/projects/.../memory/`) updated for continuity on THIS machine
- [ ] **AGENTS.md updated** if any of §4 (current state), §5 (teaching arc), §9 (failure modes) changed
- [ ] Commit + push ONLY on explicit user OK

---

*This file is the single portable source of truth for orienting a new session. Update its §4 (current state) and §5 (teaching arc) after any meaningful work unit. Everything else changes rarely.*
