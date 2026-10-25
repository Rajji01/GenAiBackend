# GenAiBackend — monorepo

Self-directed, production-minded engineering project by **Rajat Agrawal**. One repo, three
parallel tracks — each built the same way: **learn-what's-needed → build → test → harden like a
live prod system → document the trade-offs → mine it for interview prep.**

| Track | Folder | Focus | Where it's at |
|---|---|---|---|
| **GenAI (Python)** | [`narration-enrichment/`](./narration-enrichment/) | FastAPI + Instructor + Gemini → structured output, RAG, tool-calling, agentic workflows, eval, multi-model, prod-hardening | **P1–P7 + Hardening done · 360 tests** |
| **Ticketing (microservices)** | [`ticketing-platform/`](./ticketing-platform/) | Java microservices — inventory/booking/payment/notification, saga, outbox, Resilience4j, AWS foundation | **Weeks 1–3 done (124 tests) · Week 4 (AWS) design + IaC** |
| **Java baseline** | [`backend/`](./backend/) | Spring Boot production patterns (UFC/betting) — reference architecture | Largely complete |

> **New here as a human?** Start with each track's `README.md` (build log) and its
> `*_LAB.html` / `ARCHITECTURE.html` (illustrated deep-dives). For how I'd pitch this in an
> interview — RAG design, async pipelines, Forward-Deployed-Engineer deployment stories, LLD
> patterns, DSA — see **[`interview-prep/`](./interview-prep/)**.

## 🎯 Interview-prep hub

[`interview-prep/`](./interview-prep/) — cross-track, role-shaped readiness, built continuously
from the project (not a separate cram): **[FDE](./interview-prep/FDE.md)** (Forward Deployed
Engineer deployment scenarios) · **[GenAI](./interview-prep/GENAI.md)** (what's-asked ↔
what's-built) · **[HLD](./interview-prep/HLD.md)** + **[LLD](./interview-prep/LLD.md)**
(system-design walkthroughs + pattern catalog) · **[DSA](./interview-prep/dsa/)**.

## 🤖 For AI assistants (Claude, Codex, etc.) — the continuity chain

Machine-local memory does **not** survive a fresh clone or a different machine. These three
files do, and are the whole bootstrap — read them in order, every fresh start:

1. **[`FILE_GUIDE.md`](./FILE_GUIDE.md)** — the map: every file, categories, reading order.
2. **[`AGENTS.md`](./AGENTS.md)** — the rules + current state + standing conventions (§3).
3. **[`JARVIS_CHAIN.md`](./JARVIS_CHAIN.md)** — the **portable self-walk chain**: read before any
   scan/self-walk. Holds the routine, a cross-machine context stash, and an append-only log so
   continuity survives even when memory/context is cleared.

## 📖 Roadmaps

- Ticketing: [`ticketing-platform/ROADMAP.md`](./ticketing-platform/ROADMAP.md)
- GenAI: [`Jarvis_GenAI_Path.md`](./Jarvis_GenAI_Path.md) + [`narration-enrichment/ROADMAP.md`](./narration-enrichment/ROADMAP.md)
- Cross-track forward plan: [`NEXT_PATH.md`](./NEXT_PATH.md)

## 📚 Notes (per track)

- **Illustrated deep-dives** — `*_LAB.html` / `ARCHITECTURE.html` (Corner Notes & Narration Lab design systems)
- **Prose revision** with self-check questions — `LEARNING_NOTES.md` in each track
- **Study companions** (Q&A) — `ticketing-platform/TICKET_STUDY.html`, `narration-enrichment/NARRATION_STUDY.html`

## Standing conventions

- Hinglish comms · **no `Co-Authored-By` trailer on commits** · ask before push · learning-first ·
  one-service-correctly before adding more · live verification over cherry-picked demos ·
  **dual-mandate self-walk** (harden-as-prod + mine interview artifacts — `AGENTS.md` §3-12)

See `AGENTS.md` §3 for the full rule set.
