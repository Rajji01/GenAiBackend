# AGENTS.md — Bootstrap for AI assistants

**If you're a Claude/Codex/other AI session opening this repo fresh — start here.** This file exists so a new session on any machine (or a fresh clone) can orient itself in 2 minutes and pick up work correctly. Machine-local memory (in `~/.claude/...`) is not portable; this file is.

> **Rule zero:** read this file, then the pointed-to docs in **§8 Key files**, before writing any code or making any commit.

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
   - Java track uses "Corner Notes" styling (cream/amber palette) — files: `backend/CORNER_NOTES.html`, `ticketing-platform/SEAT_LOCK.html`, `ticketing-platform/SAGA_LAB.html`.
   - Python track uses "Narration Lab" styling (mint/teal) — file: `narration-enrichment/NARRATION_LAB.html`.
   - Learning-companion (Rajat's Q&A) — `ticketing-platform/TICKET_STUDY.html` (added 2026-09-18).

6. **Live verification, no cherry-picking.** Real API calls, real Docker containers, real DB. When a live result is "boring" or null, report it honestly rather than swapping for a flattering example.

7. **Don't overengineer.** Explicitly avoided: vector DB where SQLite serves (P1 RAG), numpy for one cosine function. Smallest infrastructure that satisfies the current requirement. Flag deliberate compromises in comments/docs.

8. **JUnit strategy (Week 2 update):** For learning-first sessions, **defer JUnit-writing to end-of-week clean pass**. Implement + mentally verify + document reasoning first; write proper tests over the finished shape.

---

## 4. Current state (as of 2026-09-18)

### Ticketing (Track C) — WHERE MOST OF THE ACTION IS

- **Week 1** — inventory-service ✅ **DONE** including `POST /confirm` endpoint + `afterCommit` fix. **40 tests green** (real Postgres + Redis via Testcontainers).
- **Week 2** — booking-service — Days 1–4 code done + **Day 4 LIVE-verified 2026-09-18** with 6 experiments all passing. **26 tests green**. **3 real Resilience4j bugs caught live and fixed in-session** (see `ticketing-platform/SAGA_LAB.html` Bug Museum §B4–B6).

**NOTHING is committed for Week 1 close-out or any of Week 2.** All local. User will approve commits when ready — probably 3 clean commits (Week 1 close-out, Week 2 build, Week 2 live-verify+bugfixes).

**Pending for Week 2 completion:**
- User answers 7 interview questions in `ticketing-platform/WEEK2_DESIGN.md §9` (user's own task)
- JUnit sweep for Resilience4j + docker-compose paths (deferred to end-of-week)
- User approval for commits + push

### Narration (Track B)

- Weeks 1–4 done, last commit `20cb3c6`. See `narration-enrichment/LEARNING_NOTES.md` for the full journey. **Next direction not committed to** — options: multi-provider fallback, observability, or P2 (document RAG per `Jarvis_GenAI_Path.md`).

### Java baseline (Track A)

- Treated as largely complete. Reference architecture for other tracks (RFC 7807, correlation ID pattern, exception handler shape).

---

## 5. The teaching arc (active as of 2026-09-18)

User pivoted to **learning mode** and asked to be taught what has been built, section by section, in "easy way" with code + analogies. Active study companion is `ticketing-platform/TICKET_STUDY.html`. Progress:

- ✅ **Section 1** — Problem statement (Seat entity, enum, unique constraint)
- ✅ **Q1** — Enum vs String (compile-time safety, EnumType.STRING vs ORDINAL)
- ✅ **Q2** — `@Version` alone enough for concurrency? (optimistic vs pessimistic, 4 cases where not enough)
- ✅ **Section 2** — Do stores, do lifetimes (Redis no-volume as feature, 2-store coord, alternatives)
- 📖 **Section 3 (next)** — Concurrency 2-tier defense (Redis SETNX + Postgres @Version deep)
- 📖 Sections 4–8 remaining (compensating actions, reconciliation, confirm+afterCommit, endpoint contract, cross-cutting)

When user says "section N chalu kr" — teach in chat first (rich, easy, code snippets), then batch-update `TICKET_STUDY.html` with the new section and any resulting Q&A.

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
- `AGENTS.md` (this file)
- `README.md` — one-liner + pointer here
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
- `narration-enrichment/README.md` + `LEARNING_NOTES.md` + `NARRATION_LAB.html`
- `narration-enrichment/src/` — Weeks 1–4 code

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
