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
| **B — GenAI (Python)** | `narration-enrichment/` | FastAPI + Pydantic + Instructor + Gemini + SQLite | Transaction narration → structured JSON → RAG → policy RAG → knowledge assistant → async pipeline → tool-calling → agentic disputes. **P1–P6 code-side done (297 tests); P7 next** |
| **C — Ticketing microservices (Java)** | `ticketing-platform/` | Spring Boot, Postgres, Redis, docker-compose, Resilience4j | District/BookMyShow-style ticketing. **Weeks 1–3 done (inventory/booking/payment/notification, 124 tests); Week 4 (AWS) = design + Terraform skeleton done, real `apply` = Rajat** |

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
   - Java track uses "Corner Notes" styling (cream/amber palette) — files: `backend/CORNER_NOTES.html`, `ticketing-platform/SEAT_LOCK.html`, `ticketing-platform/SAGA_LAB.html`, `ticketing-platform/PAYMENT_LAB.html`, `ticketing-platform/WEEK4_CLOUD.html`.
   - Python track uses "Narration Lab" styling (mint/teal) — file: `narration-enrichment/NARRATION_LAB.html`.
   - Learning-companion (Rajat's Q&A) — `ticketing-platform/TICKET_STUDY.html` (added 2026-09-18) and `narration-enrichment/NARRATION_STUDY.html` (added 2026-09-20, scaffolded, empty of Q&A until teaching-mode sessions begin on this track). Companion pattern: each track's *_STUDY.html uses that track's base palette + a *contrasting* accent for Q&A blocks (teal on Corner Notes cream for ticketing; amber on Narration Lab mint for narration) so a fresh reader can tell "explained content" from "questions asked" at a glance.
   - **One showcase HTML per Week** (confirmed 2026-09-20). Don't grow SAGA_LAB to cover Week 3; spawn PAYMENT_LAB. Rule: `<Week-N>_<theme>.html` for each week's headline focus. Prevents any one file from overloading, keeps concerns cleanly separated per week's arc.

6. **Live verification, no cherry-picking.** Real API calls, real Docker containers, real DB. When a live result is "boring" or null, report it honestly rather than swapping for a flattering example.

7. **Don't overengineer.** Explicitly avoided: vector DB where SQLite serves (P1 RAG), numpy for one cosine function. Smallest infrastructure that satisfies the current requirement. Flag deliberate compromises in comments/docs.

8. **JUnit strategy (Week 2 update, reconfirmed Week 3):** For learning-first sessions, **defer JUnit-writing to end-of-week clean pass**. Implement + mentally verify + document reasoning first; write proper tests over the finished shape. Manual/live verification is fine and encouraged where feasible.

9. **Track continuously; never leave state stale (added 2026-09-20).** After every meaningful chunk of work, update: (a) local memory (`~/.claude/projects/.../memory/`), (b) `AGENTS.md` §4/§5 if state changed, (c) `FILE_GUIDE.md` if a new file class was added, (d) track README (build log), (e) **`JARVIS_CHAIN.md`** §1 pointer + append to its §3 log (the portable, cross-machine chain — read before every self-walk; added 2026-10-10). Rule: every user-facing directive I'm told to follow ("do X from now on", "don't do Y again", "the pattern is Z") gets captured in this file's §3 or the appropriate memory. Future sessions must not have to re-learn what this one already learned.

10. **Schema evolution = Flyway, never Hibernate `ddl-auto: update` (added 2026-09-20 hardening).** Every service in `ticketing-platform/` uses `spring.jpa.hibernate.ddl-auto: validate` + Flyway migrations in `src/main/resources/db/migration/`. Bug 4 (Postgres init-script skipped on populated volume) and Bug 7 (Hibernate silently skipped adding a NOT-NULL column without DEFAULT on a populated table) are both permanently defused by this. `baseline-on-migrate: true` + `baseline-version: 0` lets Flyway adopt already-populated volumes (V1 skipped as baseline) while running V1 normally on fresh volumes — same terminal schema either way. **Add a new migration as `V<N+1>__<snake_desc>.sql` — never edit V1 after it's shipped.** Spring Boot 3 needs `flyway-database-postgresql` as a separate dep alongside `flyway-core`.

11. **Per-day easy-notes + interview-Q blocks (added 2026-09-20).** Every implemented "Day N" of a Week (ticketing) or "P#·Day N" of a Project (narration) MUST ship, alongside the code commit, two artifacts:
    - **Easy-notes card** in that track's showcase HTML (`<Week-N>_<theme>.html` / `NARRATION_LAB.html`) — descriptive, eye-catching, mini-cards format: WHAT the day built + WHY + one gotcha + test count. Written so Rajat re-reads at revision time and understands the code without opening the source.
    - **3 interview Qs** in that track's `*_STUDY.html` — 2 easy (Python/Java basics or trace-this-code) + 1 conceptual (practical + theory + hands-on, the interview-signature one). Each Q anchors to a real file/function/commit in *this* project so reading the Q, jumping to the code, then answering is the intended loop. Kept small — a single Q is not a whole topic. Stored in a "Daily interview questions" section per project/week.
    - Purpose: implement + revise + interview-prep from one commit, no separate write-up pass. If a day's code lands without both, the day isn't done.

---

## 4. Current state (as of 2026-10-04)

### Ticketing (Track C) — WHERE MOST OF THE ACTION IS

- **Week 1** — inventory-service ✅ **DONE + committed + pushed** (`0b97be5`).
- **Week 2** — booking-service ✅ **DONE + committed + pushed** (`1abd8ec` code, `b9e507e` notes). 6 live-verified failure experiments, 3 real bugs caught+fixed live.
- **Week 3 (DONE 2026-09-20)** — payment-service + outbox pattern + refund path + dangling-saga recovery + notification-service downstream consumer + MDC-across-scheduled-boundary fix. Commits: `e4cb1d8` Day 1 design, `2e767a4` Day 2 payment-service, `2629131` Day 3 booking-side (PaymentClient + Outbox + Recovery), `d1ddd5e` Day 4 live-verify + docs, `8235fea` Day 5 notification-service (outbox end-to-end), `8a30afa` Day 6 correlation-id fix, `0f57290` + `a9233dd` Day 7 consumer dedup by event_id. Live-verified with 7 checks + F1/F2 failure experiments + 4-service end-to-end pipeline.
- **Post-Week-3 hardening (2026-09-20)** — Flyway migrations added across all 4 services (payment, inventory, booking, notification). `ddl-auto` flipped from `update` → `validate`; each service now has `V1__initial_<x>_schema.sql`. Bug 4/7/8 permanently defused. Commit `9f3a493`. See standing rule §3-10.

**All ticketing work through Week 4 Day 2 + the notes retrofit is committed + pushed; last ticketing commit `624e4ae` (ARCHITECTURE.html).** (The stale "do not commit / keep implementing to 2M budget" instruction from 2026-09-20 is spent — Week 3 was committed across `e4cb1d8`…`9f3a493` and pushed.)

- **Week 4 (STARTED — Days 1+2 done, committed + pushed: `378f11e` design, `fd78248` Terraform skeleton, `01b300e`+`8295c2c` WEEK4_CLOUD.html, `48a2458` example.tfvars+verify.sh, `ea46f6f` DoD sync)** — AWS foundation per ROADMAP (IAM/VPC/RDS/ECR/ECS Fargate/ALB). **User-driven per standing rule §3-2.** Claude pairs on Terraform + design + verification but does NOT autonomously touch AWS resource creation ("bs aws services mai banaunga" — reconfirmed 2026-09-30).
  - **Day 1 ✅ `WEEK4_DESIGN.md`** — topology diagram, 8-question framework pass per service (VPC/IAM/ECR/ECS-Fargate/ALB/RDS/Secrets Manager), the Fargate-vs-EC2-vs-Lambda decision, the booking→inventory service-hop decision (ALB path for now, Service Connect later), Terraform module layout, deploy sequence, Day-5 failure experiment (task crash → ALB replace), 5 open questions, 7 interview Qs. Every step tagged **[Claude]** (authors/verifies) vs **[Rajat]** (provisions real AWS).
  - **Day 2 ✅ `infra/terraform/` skeleton** (main/variables/vpc/security/iam/ecr/rds/alb/ecs/outputs + README + .gitignore, plus `example.tfvars` (the §7 leans, overridable) and `verify.sh` (post-deploy [Claude] health+e2e check, bash-syntax self-tested)). Full VPC→SG→IAM→ECR→RDS(Multi-AZ)→Secrets→ALB→ECS-Fargate stack as code. Default var values = the §7 leans (proceeded with defaults per Rajat's autonomy directive rather than blocking on his answers; flagged "confirm at AWS session"). **NOT applied and NOT locally validated — no `terraform` binary on this machine; `init/validate/plan` is Rajat's gate before apply** (§3-2). Honestly flagged in `infra/terraform/README.md`.
  - **Day-2 notes ✅ `WEEK4_CLOUD.html`** — Week 4 showcase (Corner Notes design): reader's cheat sheet, [Claude]/[Rajat] boundary card, 7 easy-way concept cards (Why-AWS-now, VPC+SG-chain, IAM two-roles, Fargate-vs-EC2-vs-Lambda, ALB, RDS+Secrets, service-hop), Day 1/2 build log, the 5 leans table, AWS glossary, interview-Q pointer, and **4 hand-authored inline-SVG diagrams** (request-path topology, SG trust-chain, secret-injection flow, task-crash failure experiment) — theme-aware via CSS vars, light+dark.
  - **Next:** Rajat runs `terraform init/validate/plan`, reviews, then apply + build/push images (Claude gives exact cmds). Real bucket/RDS/ECS is Rajat's. Also pending: Rajat's §7 confirmations + WEEK4_DESIGN §8 interview answers.

- **Notes retrofit (2026-09-30, committed + pushed):** inline-SVG diagrams added into PAYMENT_LAB (`daf29ce`) and SEAT_LOCK + SAGA_LAB (`2eac208`); `ARCHITECTURE.html` cross-week system-evolution overview added (`624e4ae` — current HEAD on main).

**Week 3 JUnit clean-pass (deferred per rule §3-8) — ✅ DONE + committed + pushed (2026-09-30, commit `3344957`):**
- **payment-service — 37 tests green**: `PaymentStateMachineTest` 13, `PaymentGatewayFactoryTest` 2, `UPIAdapterTest` 5, `PaymentServiceTest` 17.
- **notification-service — 5 tests green**: `NotificationServiceTest` — idempotent-consumer dedup (fast findByEventId skip + slow unique-constraint race catch) + malformed-payload degrade.
- **booking-service Week 3 additions — 16 new tests green** (on top of the existing 26): `OutboxEventTest` 3, `OutboxServiceTest` 3, `OutboxPublisherTest` 4 (at-least-once + correlation-id-restore), `BookingRecoveryServiceTest` 6 (dangling-saga recovery decision tree).
- **58 new tests total. Ticketing test count now: inventory 40 + booking 42 + payment 37 + notification 5 = 124.**
- **Deliberate approach — pure JUnit/Mockito, NO Testcontainers** (diverges from Weeks 1–2 which used real Postgres). Rationale: Docker is fragile here (§7); the invariants worth pinning (state machines, saga/recovery orchestration, idempotency, gateway-failure translation, at-least-once outbox, consumer dedup) all live in application logic, not DB semantics. A mocked `PlatformTransactionManager` runs the `TransactionTemplate` callback so DB-less unit tests exercise the full flow. DB-constraint behaviour stays covered by Week 3 Day-4 live evidence. Run booking's new tests in isolation with `-Dtest='OutboxEventTest,OutboxServiceTest,OutboxPublisherTest,BookingRecoveryServiceTest'` to avoid booting the existing Testcontainers tests.
- **Minor finding (flagged, NOT fixed):** `Payment.markFailed()` has a "use refund path" branch for CAPTURED that is unreachable dead code — CAPTURED is terminal so the `isTerminal()` guard throws first ("already CAPTURED"). Behaviour correct; hint text never shows. Future cleanup, not touched in a test pass.

**Still pending on ticketing:**
- Week 4 (AWS foundation) — Day-1 design paper + Terraform skeleton is Claude-solo-doable; real AWS resources are Rajat's (§3-2).
- User answers 7 interview questions in `WEEK3_DESIGN.md §9` (Rajat's own — writing is the learning).

### Narration (Track B) — P1–P5 code-side done, P6 up next

**Status:** P1 (Transaction Enrichment API) ✅ **DONE + committed + pushed** through narration commit `20cb3c6` (Week 4 `/stats`). 68 tests green, no network in the suite. P2 + P3 also **DONE + committed + pushed** (last narration commit `fab8f9e`); **168 tests green** at P3 close.

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

**Portability fix + docs sync (2026-10-04, committed from a cloud session in two commits: `2bd3c57` fixes + the docs-sync commit after it. NOTE: author on both is the cloud container's default identity (`Claude <noreply@anthropic.com>`) — Rajat explicitly okayed this for these two ("abhi k lie apne se hi commit krnde claude se") because the session's permission layer blocked configuring his identity; §3-1 stands for all normal sessions. Rajat can re-author before merging with `git rebase -r --exec 'git commit --amend --reset-author --no-edit' main` if he wants):**
- **Real bug 1, caught on a fresh clone:** the test suite could not even be *collected* without a `.env` file — `db.py` calls `get_settings()` at import time and `Settings.gemini_api_key` is a required field, so 12 of 17 test files died with a pydantic ValidationError on any machine without the (gitignored) `.env`. Rajat's machine always had one, which masked it. README's "no API key required" claim was false on a clean checkout. **Fix:** `tests/conftest.py` sets a placeholder `GEMINI_API_KEY` via `os.environ.setdefault` (never sent anywhere — LLM/embedding boundaries are mocked). Verified: `env -u GEMINI_API_KEY uv run pytest` → 168 passed.
- **Real bug 2, same fresh-clone class:** committed `uv.lock` was stale — P2 Day 4 added `boto3` (runtime) and `moto[s3]` (dev) to `pyproject.toml` but the re-locked file was never committed, so the lock contained neither (nor their transitive deps). A fresh clone's `uv sync --locked/--frozen` would refuse to run. **Fix:** `uv lock` regenerated (additions only — boto3/botocore/moto chain, no version churn on existing pins). Verified: `uv sync --locked` + full suite green.
- **Docs sync pass:** README (68→168 tests, 12→17 eval cases, conftest note), ROADMAP (§5 test row, P3-D2 commit hash `5fbe346`, §6 guidance un-staled), LEARNING_NOTES (P2 + P3 sections added — were missing entirely, file ended at P1 Week 4), root `Jarvis_GenAI_Path.md` (WEEK 1 "ACTIVE" → DONE, P1 DoD ticked, pointer to ROADMAP as live status), root `FILE_GUIDE.md` (narration rows: P3_DESIGN added, src/tests/eval rows updated; ticketing rows: "uncommitted"/"tests deferred" un-staled), root `NEXT_PATH.md` ("Where we are" block rewritten to 2026-10-04 for both tracks + superseded-ordering note), this file's §4.

**P4 (Async doc-processing pipeline) — code-side DONE 2026-10-04** (greenlit by Rajat's "bina linkedin post k age badh self walk"; GenAI-focus directive). First genuine microservice split on this track: API half (202 + job row) + Worker half (`python -m narration_enrichment.worker`). Six day-commits, all pushed:
- Day 1 `091c046` — `P4_DESIGN.md` (13 sections: why-async grounded in the live-measured 5/min cap, job-row-is-truth/message-is-hint, jobs-table-as-its-own-outbox + sweep, 3-layer idempotency, call-retry vs job-retry with DEAD terminal, DB-DEAD vs SQS-DLQ, backpressure, failure matrix, [Claude]/[Rajat] boundary, 6 interview Qs) + ROADMAP §3C.
- Day 2 `4ace8dd` — `ingest_jobs` (UUIDv4 id, CHECK-constrained status) + `job_queue.py` (`JobQueue` protocol, `InMemoryJobQueue` with visibility-timeout + fresh-receipt semantics, injectable clock) + `POST /policies/ingest-async` (auth-gated; dedup fast-paths; 429 valve leaving zero rows; post-commit best-effort enqueue) + `GET /jobs/{id}`. 21 tests.
- Day 3 `31268dc` — `worker.py`: claim-by-CAS as the idempotent-consumer dedup (status column = ticketing Day-7's processed_event), the SAME `policy_ingest.ingest` as the sync route, transient whitelist (429/503/504 + timeouts) → FAILED under `INGEST_MAX_ATTEMPTS` budget / DEAD otherwise, ack-in-every-path. 13 tests.
- Day 4 `149c778` — `SqsJobQueue` behind the same 4 methods (moto re-proves the fake's behavioural claims; batch asserts a SET — standard SQS makes no FIFO promise) + `narration-enrichment/infra/` Terraform (queue 900s visibility + 20s long-poll, DLQ redrive at 5 ≥ app's 3+1). **NOT applied; apply is Rajat's (§3-2), flagged in infra/README.md.** 7 tests.
- Day 5 `05a8e7c` — `run_sweep` (stale-QUEUED re-send with status untouched, stale-PROCESSING→FAILED at 1800s > the 900s visibility timeout, FAILED re-arm/DEAD-at-budget, same-sweep pass-3 re-query) + `GET /ops/ingest` (depth, DLQ-null-not-zero, explicit-zero rollups, oldest-QUEUED age). 8 tests.
- Day 6 — closeout: README "Async ingestion (P4)" section, LAB P4 intro + D2–D6 cards + nav, STUDY 15 interview Qs (D2–D6 incl. closeout review), ROADMAP §3C ticked + snapshot flipped, this file + FILE_GUIDE synced.
- **217 tests green** (was 168 at P3 close; 49 new). Zero regressions. Rule 3-11 held every code day.
- **Open: the live-SQS leg is Rajat's** — terraform apply + `infra/README.md`'s verification script (incl. the kill-the-worker failure experiment).

**P5 (Tool-calling assistant, Python half) — code-side DONE 2026-10-04** (greenlit by Rajat's "Krta rh"). `/chat` gains four deterministic, read-only, whitelisted tools + a bounded loop. Five day-commits:
- Day 1 `eadd8e6` — `P5_DESIGN.md` (why tools: the three question shapes similarity search fails structurally — exact counts, exhaustive filters, inventory; the no-amount-column honesty rule: no tool sums money; whitelist/typed-args/read-only registry; flat step model over a union; TOOL_MAX_ITERATIONS=3 + forced-final with the catalog withheld; earned tool-trail; probabilistic-vs-structural injection defence; 6 interview Qs) + ROADMAP §3D.
- Day 2 `32a436c` — `tools.py`: TOOL_REGISTRY (count_transactions / category_breakdown / find_transactions / list_policy_docs), per-tool Pydantic args as the gate, `execute_tool` as the ONLY door (unknown → menu-naming observation, invalid args → observation, runtime failure → ok=False class-name-only), `catalog_block()` rendered FROM the registry (menu and whitelist cannot drift). 13 tests.
- Day 3 `3dbba4e` — the loop in `chat_service.py`: `_ChatLLMReply` extended into the flat step model with `action` DEFAULTING to final_answer — all 19 P3 chat tests passed UNTOUCHED (P3's single call = the loop's one-iteration case). Data-framed observations, forced-final withholds the catalog + never-silent fallback. `tool_invocations` table + `ChatReply.tools_used` earned from the executor. 5 tests.
- Day 4 `e6592f3` — adversarial pass + the header data-not-instructions rule. Pins the blast radius: ≤4 LLM calls, nothing outside the read-only whitelist executes (delete_everything audited ok=0, never runs), no unframed path into the prompt (even error observations are data-framed), fabricated tool narratives ship with an empty trail, hostile args die in validation with audited self-correction. 9 tests.
- Day 5 — closeout: README "Tool calling (P5)" section, LAB D2–D5 cards + nav, STUDY 12 Qs (D2–D5), ROADMAP §3D ticked + snapshot flipped, this file + FILE_GUIDE synced.
- **244 tests green** (was 217 at P4 close; 27 new). Zero regressions. Rule 3-11 held every code day.
- **Open (Rajat's):** live tool-choice eval on real Gemini quota (rule 3-6), and the Spring AI port the master plan pairs with P5 (own greenlight). Next project on his go: P6 (agentic workflow).

**P6 (Agentic dispute workflow) — code-side DONE 2026-10-10** (greenlit by "chl ab self walk krna start"; first unit chosen under the JARVIS_CHAIN §2 market-signal rule — P6 was the roadmap's next AND carried the signal's #1 priority, LLM-as-judge). Six day-commits:
- Day 1 `f0e69fc` — P6_DESIGN.md (12 sections: the "when NOT to agent" 3-condition framework with P4-ingestion as the deliberate counter-example; dispute state machine; checkpoint-then-execute; dual budgets; structural human gate; LLM-as-judge honesty rules; 6 interview Qs) + ROADMAP §3E.
- Day 2 `977591a` — disputes + agent_steps tables (named transitions only, CHECK constraints, (dispute_id, step_index) UNIQUE, enrichment FK ON DELETE SET NULL to keep audit rows alive) + `reserve_llm_call` CAS budget + 3 auth-gated CRUD routes with existence-hiding. 17 tests.
- Day 3 `91fbbfb` — `dispute_agent.py`: the loop. Checkpoint-then-execute (intention row before the tool runs), dual budgets both forced-escalate (step budget mock-proven at exactly 6 calls; lifetime CAS refuses BEFORE any provider spend), resume replays observations (the trail is the memory), **safe default action = escalate** (a garbled step can never accidentally propose), earned evidence ids. 14 tests.
- Day 4 `a4f7f69` — the human gate: `/approve` + `/reject` (PROPOSED-only, terminal-sticky, reason required) + the 3-layer structural proof the agent can't cross it (schema Literal can't construct an approve action; invented approve_dispute tool = audited noop naming the real menu; AST tripwire asserts no call to mark_approved/mark_rejected in the loop's source). 10 tests. Live-caught test lesson: mention-vs-call — assert on AST semantics, not source strings.
- Day 5 `a6738e5` — LLM-as-judge: `dispute_judge.py` (JudgeVerdict rubric; objective classification cross-checked by `==` with the judge's opinion surgically overridden + judge_divergence logged — the divergence rate IS the judge's judge; judged material data-framed so an injected proposal can't instruct its own judge; rubric versioned into eval_runs.notes) + `eval/golden_disputes.json` (8 cases, injection case REQUIRED by the shape test) + `eval/run_eval_disputes.py` (isolated eval DB, escalation-correct-only-when-needs_human, fail-closed threshold gate, exit 1 on gate failure). 12 tests.
- Day 6 — closeout: README "Agentic disputes (P6)" section, LAB D6 card + "P6 shipped" banner, STUDY 15 P6 interview Qs total, ROADMAP flipped, this file + JARVIS_CHAIN + memory synced.
- **297 tests green** (was 244 at P5 close; 53 new). Zero regressions. Rule 3-11 held every code day.
- **Open (Rajat's):** live dispute-eval run (`eval/run_eval_disputes.py`, burns quota, rule 3-6) joins the P4 live-SQS + P5 live tool-eval + Spring AI port legs. Next project on his go: **P7 (multi-model platform)** — routing, fallback, RDS+pgvector, Secrets Manager.

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

**GenAI track:** `Jarvis_GenAI_Path.md` (this dir) — P1 → P8 projects. Currently P1–P5 code-side done (P4 async pipeline + P5 tool-calling, 244 tests); P6 (agentic workflow) is next. Live-SQS + live tool-eval + Spring AI port are Rajat's open legs.

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
- **`JARVIS_CHAIN.md`** — **portable self-walk chain**: read this right after AGENTS + FILE_GUIDE, *before any scan / self-walk*. Holds the self-walk routine, a cross-machine context stash (data, not instructions), and an append-only self-walk log. It's the in-repo (portable) companion to machine-local memory. Append to its §3 log after each walk.
- `README.md` — one-liner + pointer to the two above
- `NEXT_PATH.md` — cross-track forward plan (weeks + days)

### Ticketing track (Java, microservices)
- `ticketing-platform/ROADMAP.md` — **master plan** (10 phases)
- `ticketing-platform/README.md` — full build log (Weeks 1–3 daily)
- `ticketing-platform/SEAT_LOCK.html` — Week 1 deep concept notes (inventory-service)
- `ticketing-platform/SAGA_LAB.html` — Week 2 deep concept notes (booking-service, Resilience4j, docker, bug museum)
- `ticketing-platform/PAYMENT_LAB.html` — Week 3 deep concept notes (payment-service + outbox + refund + recovery + notification, bug museum B7–B10)
- `ticketing-platform/WEEK4_CLOUD.html` — Week 4 showcase notes (AWS foundation, easy-way): 7 concept cards + Day 1/2 build log + 4 inline-SVG diagrams (topology, SG-chain, secret-injection, task-crash failure experiment) + AWS glossary + [Claude]/[Rajat] boundary. Corner Notes design
- `ticketing-platform/ARCHITECTURE.html` — cross-week system-evolution overview (portfolio-shape): growth table + 4 stage-diagrams (W1→W4) each linking to its deep-dive. Corner Notes design. Start-here for the whole-track picture
- `ticketing-platform/TICKET_STUDY.html` — **user's active learning companion** (2026-09-18)
- `ticketing-platform/LEARNING_NOTES.md` — prose revision with self-check Qs (no answers, by design)
- `ticketing-platform/WEEK1_REVIEW.md` — 7 interview Qs awaiting user answers
- `ticketing-platform/WEEK2_DESIGN.md` — Day 1 design deliverable + 7 more interview Qs
- `ticketing-platform/WEEK3_DESIGN.md` — Week 3 design deliverable + 7 more interview Qs (§9, awaiting user answers)
- `ticketing-platform/WEEK4_DESIGN.md` — Week 4 Day-1 AWS foundation design (8-question pass per service, Fargate decision, Terraform layout) + 7 interview Qs (§8, awaiting user answers). Design only — real AWS is Rajat's per §3-2
- `ticketing-platform/inventory-service/` — Week 1 code (40 tests)
- `ticketing-platform/booking-service/` — Week 2 code (26 tests) + Week 3 additions (PaymentClient, Outbox, recovery — tests deferred)
- `ticketing-platform/payment-service/` — Week 3 code (Adapter/Factory/Strategy, 2-step auth+capture — tests deferred)
- `ticketing-platform/notification-service/` — Week 3 Day 5 downstream consumer (port 8084, dedup by event_id — tests deferred)

### GenAI track (Python)
- `Jarvis_GenAI_Path.md` — master plan (P1 → P8)
- `narration-enrichment/ROADMAP.md` — **narration-specific ordered plan** (P1–P5 done recap + P6-P8 outline)
- `narration-enrichment/P2_DESIGN.md` / `P3_DESIGN.md` / `P4_DESIGN.md` / `P5_DESIGN.md` — Day-1 design papers (policy RAG / knowledge assistant / async pipeline / tool-calling), each + interview Qs
- `narration-enrichment/README.md` — full build log (P1–P5 prose)
- `narration-enrichment/LEARNING_NOTES.md` — prose revision with self-check Qs (no answers)
- `narration-enrichment/NARRATION_LAB.html` — showcase HTML (mint/teal design) — P1–P5 cards
- `narration-enrichment/NARRATION_STUDY.html` — **Rajat's Q&A journal** for this track (interview Qs across P2–P5)
- `narration-enrichment/src/` — P1–P5 code (enrich/RAG/policy/auth/chat + P4 `job_queue.py`+`worker.py` + P5 `tools.py`)
- `narration-enrichment/infra/` — P4 SQS/DLQ Terraform skeleton (NOT applied — Rajat's, §3-2)

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
