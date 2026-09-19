# FILE_GUIDE.md — the map of every file in this repo

**For AI agents or new humans:** if you were handed just this one file, you would know what everything in the repo is for, in what order to read them, and how they relate. Pair this with `AGENTS.md` (which covers the rules and current state); this file covers the **structure**.

---

## 1. Reading order — if you have never seen this repo

For a **new agent**, read in this exact order. Each step is short and unlocks the next:

1. **This file (`FILE_GUIDE.md`)** — the map. You're reading it.
2. **`AGENTS.md`** — the rules, current state, standing conventions, environment quirks. **Non-negotiable rules live here.**
3. **`README.md`** (root) — welcome, one-liner, links back to the above two.
4. **`ticketing-platform/ROADMAP.md`** — the master plan for the ticketing track (10 phases).
5. **`Jarvis_GenAI_Path.md`** — the master plan for the GenAI (Python) track (P1→P8).
6. **`NEXT_PATH.md`** — synthesized cross-track forward plan, week-by-week.

After that, drop into whichever track you're working on and read that track's `README.md` + `LEARNING_NOTES.md` + `*_LAB.html`.

---

## 2. The 6 file categories — the mental model

Every file in this repo falls into exactly one of these six buckets. Once you know a file's category, its purpose is obvious.

| Category | Icon | What it is | Reader | Update triggers |
|---|---|---|---|---|
| **Bootstrap / meta** | 🤖 | Files that orient any new reader (human or AI) | Any first-time visitor | State change, new rule |
| **Plans / roadmaps** | 🗺️ | What is planned to happen next (forward-looking) | Session planning, weekly kickoff | New phase, direction change |
| **Build logs** | 📖 | Record of what has been completed (backward-looking) | Recap, "what happened here" | Every completed work unit |
| **Deep concept HTMLs (showcase)** | 🔨 | "What I built and why" for portfolio / others | Portfolio viewers, interviewers, later self | End of each week / phase |
| **Personal learning (Rajat's Q&A)** | 📘 | Teaching companion — sections + Q&A captured | Rajat's own revision | Every taught section |
| **Design / interview** | 📝 | Specs for upcoming work + unanswered interview Qs | Design step, weekend review | Start of each week |

Plus utility files (code, tests, config) which are self-explanatory and covered per-service below.

---

## 3. Complete file map

### 🏠 Repo root (`GenAiBackend/`)

| File | Category | Purpose | Size (approx) |
|---|---|---|---|
| **`FILE_GUIDE.md`** | 🤖 Bootstrap | THIS FILE — directory index for the whole repo | this |
| **`AGENTS.md`** | 🤖 Bootstrap | Rules, current state, workflow, standing conventions, environment quirks, key files map, common failure modes | ~12 KB |
| **`README.md`** | 🤖 Welcome | One-page overview + pointer to `AGENTS.md` | ~1.5 KB |
| **`NEXT_PATH.md`** | 🗺️ Cross-track plan | Combined forward plan for BOTH tickets + narration, week-by-week + day-by-day. `[PLAN]` markers = verbatim from source, `[PROPOSAL]` = my forward-looking suggestion | ~17 KB |
| **`Jarvis_GenAI_Path.md`** | 🗺️ Roadmap | Master plan for GenAI/Python track — P1→P8 projects | ~6 KB |
| **`JARVIS_OPENAI_CONTEXT.md`** | 📜 Historical | Frozen context written by an OpenAI-based session mid-Week-4 narration (2026-09-17). Useful for background; current state lives in `AGENTS.md` §4 | ~7 KB |

### 🎫 Ticketing track (`ticketing-platform/`)

**Top-level docs:**

| File | Category | Purpose |
|---|---|---|
| **`README.md`** | 📖 Build log | Full week-by-week + day-by-day daily entries. "What has been completed" |
| **`ROADMAP.md`** | 🗺️ Master plan | 10 phases (Weeks 2 → 15+). "What is next." SUPERSEDES `codes Practice/Jarvis_Architect_Path.md` |
| **`WEEK1_REVIEW.md`** | 📝 Interview Qs | 7 interview questions for Week 1 close-out. Rajat's own answers pending. |
| **`WEEK2_DESIGN.md`** | 📝 Design + Qs | Day 1 design deliverable (state machine, orchestration case, saga design, API contract, sequence diagrams) + 7 more interview questions |
| **`WEEK3_DESIGN.md`** | 📝 Design + Qs | Day 1 deliverable for Week 3 (payment-service state machine, Adapter/Factory/Strategy, outbox pattern, saga rollback failure matrix, dangling recovery, sequence diagrams) + 7 more interview questions |
| **`LEARNING_NOTES.md`** | 📖 Prose revision | Prose deep notes with self-check questions at end of each section. **No answers by design** — revision tool |
| **`SEAT_LOCK.html`** | 🔨 Showcase HTML | Week 1 (`inventory-service`) deep concept + build log. Corner Notes design (cream/amber) |
| **`SAGA_LAB.html`** | 🔨 Showcase HTML | Week 2 (`booking-service`) deep concept + build log. Same Corner Notes design. Includes Day 4 LIVE EVIDENCE card with real terminal output + 6-entry bug museum |
| **`PAYMENT_LAB.html`** | 🔨 Showcase HTML | Week 3 (`payment-service` + outbox + refund + recovery) deep concept + build log. 10 concepts, 4 days, 4-entry bug museum (Bugs 7-10), LIVE EVIDENCE card, task ledger, decision log, tech glossary. Corner Notes design. |
| **`TICKET_STUDY.html`** | 📘 Personal learning | Rajat's Q&A journal. Sections + questions + answers captured from live teaching. **Distinct from showcase HTMLs** — this is study/revision, not portfolio |

**Config / deployment:**

| File | Purpose |
|---|---|
| `docker-compose.yml` | Local stack: Postgres + Redis + inventory-service + booking-service. One command up |
| `.env.example` | Template for `.env`. DB credentials, port overrides, inventory base URL |
| `db-init/create-*-db.sh` | Init scripts that create the per-service Postgres databases on the shared server. **Only runs on fresh volume** — see AGENTS.md §7 for the trap. Post-Week-3: schema-within-a-database is now owned by Flyway, but these scripts still create the empty databases themselves |
| `<service>/src/main/resources/db/migration/V*__*.sql` | **Flyway migrations** (2026-09-20 hardening). Every service uses `ddl-auto: validate` + Flyway. Add new migrations as `V<N+1>__<snake_desc>.sql`; never edit a shipped V1. See AGENTS.md §3 rule 10 |

**Services:**

- **`inventory-service/`** — Week 1's Spring Boot service (seats, holds, availability, confirm). Complete + tested + committed.
- **`booking-service/`** — Week 2's saga orchestrator + Week 3 additions (PaymentClient, Outbox, BookingRecoveryService, refund path, EventBus HTTP push, correlation-id-in-outbox-row fix).
- **`payment-service/`** — Week 3's service (Adapter+Factory+Strategy for payment methods, 2-step auth+capture, refund lifecycle). Committed + live-verified.
- **`notification-service/`** — Week 3 Day 5's downstream consumer (port 8084). POST /notifications/receive webhook + read endpoints. Committed + live-verified end-to-end.

Each service directory has the standard Maven layout:
- `pom.xml`, `mvnw`, `mvnw.cmd`, `.mvn/` — build
- `Dockerfile`, `.dockerignore` — containerize
- `README.md` — dev-facing service doc (API surface, config keys, run instructions, package layout)
- `src/main/java/com/ticketing/{inventory,booking,payment}/**` — source
- `src/main/resources/application.yml` — config
- `src/test/java/**` — tests (Weeks 1+2 have them; Week 3 tests deferred per user directive)

**Booking-service Week 3 packages:**
- `outbox/` — `OutboxEvent`, `OutboxRepository`, `OutboxService` (write within tx), `OutboxPublisher` (`@Scheduled` drain), `EventBus` (stub, will become SNS in Phase 3)

**Test count check (as of last commit `8a30afa`):**
- `inventory-service`: 40 tests green
- `booking-service`: 26 tests green (old `BookingSagaServiceTest` deleted with Week 3's saga rewrite; tests get rebuilt at end-pass per user directive)
- `payment-service`: 0 tests (Week 3, deferred)
- `notification-service`: 0 tests (Week 3 Day 5, deferred)

### 🐍 Narration track (`narration-enrichment/`)

Python/FastAPI/Gemini/Instructor/RAG track. Weeks 1–4 done.

| File | Category | Purpose |
|---|---|---|
| `README.md` | 📖 Build log | Week-by-week daily entries |
| `LEARNING_NOTES.md` | 📖 Prose revision | Self-check Qs, no answers |
| `NARRATION_LAB.html` | 🔨 Showcase HTML | Deep concept HTML — **Narration Lab design (mint/teal)**, distinct from Java-track's Corner Notes |
| `Dockerfile`, `docker-compose.yml` | Config | Local run |
| `pyproject.toml`, `uv.lock` | Config | Python deps (uv-managed) |
| `src/narration_enrichment/**` | Code | main.py, service.py, config.py, models.py, db.py, rag.py, rate_limiter.py, correlation.py |
| `tests/**` | Tests | pytest (LLM boundary mocked, real DB via in-memory SQLite + StaticPool) |
| `eval/**` | Eval | Golden dataset + run_eval.py |
| `narration_enrichment.db` | Runtime | SQLite persistence (gitignored likely) |

### ☕ Original Java baseline (`backend/`)

UFC/betting Spring Boot backend. Reference architecture. Treated as largely complete.

| File | Purpose |
|---|---|
| `LEARNING_NOTES.md` | Prose revision |
| `CORNER_NOTES.html` | Original Corner Notes design system HTML — the template for `SEAT_LOCK.html` + `SAGA_LAB.html` |
| `HELP.md` | Spring Initializr generated help |
| `src/**` | Java code (Spring Boot 3, JPA, MySQL, Flyway, DTOs, optimistic locking) |
| `pom.xml`, `mvnw*` | Maven build |

---

## 4. The 3 HTML design systems — which is which

| Design system | Colors | Used in | Vibe |
|---|---|---|---|
| **Corner Notes** | Cream `#F5F1E8` bg, amber `#A9761F` accent | `CORNER_NOTES.html`, `SEAT_LOCK.html`, `SAGA_LAB.html` | Warm, notebook, boxing/UFC |
| **Narration Lab** | Mint `#EDF1F2` bg, teal `#0E8B8D` accent | `NARRATION_LAB.html` | Cool, scientific, lab-notebook |
| **Ticket Study** | Corner Notes cream base + teal Q&A accent | `TICKET_STUDY.html` | Hybrid — same as Corner Notes but Q&A blocks visually distinct via teal borders |

**Deliberate:** Java tracks use Corner Notes for visual continuity. Python track uses Narration Lab so at a glance you can tell which track you're viewing. TICKET_STUDY overlays teal on Corner Notes to distinguish concept blocks (amber) from Q&A blocks (teal).

---

## 5. File relationships — who references whom

### Bootstrap chain (a new session's reading path)
```
FILE_GUIDE.md → AGENTS.md → track ROADMAP → track README (build log) → track LAB HTML (deep concepts)
                          → NEXT_PATH.md (for cross-track view)
```

### Learning arc chain (active teaching)
```
TICKET_STUDY.html sections/Q&A ← taught from ← SEAT_LOCK / SAGA_LAB ← code in inventory-service / booking-service
LEARNING_NOTES.md ← prose revision covering the same material
WEEK1_REVIEW.md / WEEK2_DESIGN.md ← interview Qs to be answered independently
```

### Docs referenced from AGENTS.md §8 (key files map)
AGENTS.md is the single source of truth for what files matter for the current work; it points to every file listed in this guide.

### Ticketing service dependency
```
booking-service (Week 2)  ─── HTTP ───►  inventory-service (Week 1)
    │                                        │
    ▼                                        ▼
  Postgres (booking DB)              Postgres (inventory DB) + Redis
   [same Postgres server, two databases via db-init/]
```

### Design system origin
```
backend/CORNER_NOTES.html (original)
        │
        ├──► ticketing-platform/SEAT_LOCK.html    (copied styling, Week 1)
        ├──► ticketing-platform/SAGA_LAB.html     (copied styling, Week 2)
        └──► ticketing-platform/TICKET_STUDY.html (copied styling + teal Q&A extension)

narration-enrichment/NARRATION_LAB.html (separate, mint/teal design system)
```

---

## 6. Legend / conventions

| Symbol / term | Meaning |
|---|---|
| 🤖 Bootstrap | Meta-doc for AI agents / fresh readers |
| 🗺️ Plan | Forward-looking (what should happen) |
| 📖 Build log | Backward-looking (what did happen) |
| 🔨 Showcase | Deep-concept HTML for portfolio / others |
| 📘 Personal | Rajat's own learning / revision |
| 📝 Design/Interview | Spec + unanswered Qs |
| 📜 Historical | Frozen; superseded but kept for reference |
| ⚙️ Config | Deployment / runtime |

**Terminology:**
- "Track" = a parallel project stream. Repo has 3 tracks: Java baseline (`backend/`), GenAI Python (`narration-enrichment/`), Ticketing microservices (`ticketing-platform/`).
- "Phase" = ticketing roadmap unit (Phase 0 → Phase 8+). See `ticketing-platform/ROADMAP.md`.
- "Project" = GenAI roadmap unit (P1 → P8). See `Jarvis_GenAI_Path.md`.
- "Showcase" vs "Study" HTMLs — showcase is for others to read; study is Rajat's personal Q&A companion.

---

## 7. State that lives OUTSIDE this repo — pointers

Some information intentionally does NOT live in a repo file:

| State | Where it lives | Why not in repo |
|---|---|---|
| **Local memory files** | `~/.claude/projects/C--Users-Lenovo-Downloads-mmstuff-dev-codes-Practice-java-GenAiBackend/memory/` on this machine | Machine-bound, not portable. Duplicated in structure by `AGENTS.md` for the portable version |
| **Recent git history** | `git log` | Duplicating history in a file drifts. Use `git log --oneline` |
| **Currently-running processes** | OS process table + Docker daemon | Ephemeral by nature |
| **User's interview answers** | Rajat writes them directly in `WEEK1_REVIEW.md` / `WEEK2_DESIGN.md` when ready | By design — writing is the learning |
| **JUnit tests for Resilience4j behavior** | Not yet written (deferred per user directive to end-of-Week-2 clean pass) | Explicit deferral, see AGENTS.md §3 rule 8 |
| **The `.env` file** (real, with actual creds) | Local only, gitignored | Secrets |

---

## 8. Discovery patterns — "how do I find X"

| I need… | Read this file |
|---|---|
| The rules of engagement | `AGENTS.md` §3 (Standing rules) |
| Current work state | `AGENTS.md` §4 (Current state) |
| What's next on the ticketing track | `ticketing-platform/ROADMAP.md` |
| What's next on the GenAI track | `Jarvis_GenAI_Path.md` |
| Combined next steps | `NEXT_PATH.md` |
| Deep understanding of Week 1 (ticketing) | `ticketing-platform/SEAT_LOCK.html` |
| Deep understanding of Week 2 (ticketing) | `ticketing-platform/SAGA_LAB.html` |
| Deep understanding of narration | `narration-enrichment/NARRATION_LAB.html` |
| Rajat's active learning progress | `ticketing-platform/TICKET_STUDY.html` + `AGENTS.md` §5 |
| Interview questions to answer | `ticketing-platform/WEEK1_REVIEW.md` + `WEEK2_DESIGN.md` |
| Code for the booking flow | `ticketing-platform/booking-service/src/**` |
| Code for the seat/hold logic | `ticketing-platform/inventory-service/src/**` |
| How to run everything locally | `ticketing-platform/README.md` "Run locally" section |
| Endpoint contracts | Each `*-service/README.md` |
| A specific bug's story | `SAGA_LAB.html` Bug Museum (B1-B6) or `SEAT_LOCK.html` |
| Resilience4j gotchas | Local memory `resilience4j_bug_museum.md`, or `SAGA_LAB.html` §B5 §B6 |
| Docker patterns on this machine | Local memory `docker_local_dev_patterns.md`, or `AGENTS.md` §7 |

---

## 9. Update discipline — how to keep THIS file current

**When adding a new file**, add a row to §3 (Complete file map) in the appropriate track. State the category, purpose, and (if relevant) size.

**When adding a new design system** (unlikely — three is enough), add a row to §4.

**When adding a new track** (very unlikely), add its subsection to §3 with the standard layout.

**When the reading order should change** (e.g. a new critical file is added), update §1.

**Categories in §2 rarely change** — they're a stable mental model. Only add a new category if a genuinely new kind of file appears.

**Trigger:** any new file added at the repo root, or any new top-level file in a track (`ticketing-platform/`, `narration-enrichment/`, `backend/`). Config/code files inside `src/**` don't need a new row here — they're covered by the "each service directory has standard Maven/Python layout" pattern.

---

## 10. What this file is NOT

- ❌ Not a build guide — see each track's `README.md`
- ❌ Not a rulebook — see `AGENTS.md`
- ❌ Not a roadmap — see `ROADMAP.md` / `Jarvis_GenAI_Path.md` / `NEXT_PATH.md`
- ❌ Not a tutorial — see `LEARNING_NOTES.md` per track or `TICKET_STUDY.html`
- ❌ Not a status report — see git log + `AGENTS.md` §4

It is **only** a map. A "you-are-here" board.

---

## 11. One-paragraph summary (for a very fast reader)

> This repo hosts three parallel engineering-learning tracks in one place. **`backend/`** is a Java Spring Boot baseline (UFC/betting, largely complete). **`narration-enrichment/`** is Python + FastAPI + Gemini + Instructor + RAG (P1 done through Week 4). **`ticketing-platform/`** is a Java microservices track building a District/BookMyShow-style booking system — Week 1 (inventory-service) done, Week 2 (booking-service saga) done through Day 4 including live-verify. Every track has: a **`README.md`** (build log), a **`LEARNING_NOTES.md`** (prose revision), and a **deep concept HTML** (`SEAT_LOCK.html` / `SAGA_LAB.html` for ticketing, `NARRATION_LAB.html` for narration, `CORNER_NOTES.html` for backend). The ticketing track additionally has **`ROADMAP.md`** (master plan), **`WEEK1_REVIEW.md`** and **`WEEK2_DESIGN.md`** (interview questions), and **`TICKET_STUDY.html`** (Rajat's personal Q&A journal, distinct from showcase). Repo-root **`AGENTS.md`** is the portable bootstrap for AI agents (rules + current state); **`NEXT_PATH.md`** is the cross-track forward plan; **`Jarvis_GenAI_Path.md`** is the GenAI roadmap. Standing rules: no `Co-Authored-By` trailer on commits, ask before push, subdirs never separate repos, learning-first over test-first.

That paragraph, plus this file's tables, gives a new agent everything.

---

*File is maintained alongside `AGENTS.md`. If in doubt about a file's purpose, this map is the answer. If the answer is not here, add it.*
