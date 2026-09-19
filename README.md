# GenAiBackend — monorepo

Self-directed engineering-mentorship project by **Rajat Agrawal**. Three parallel tracks in one repo:

| Track | Folder | Focus |
|---|---|---|
| **Java baseline** | [`backend/`](./backend/) | Spring Boot production-grade patterns (UFC/betting) |
| **GenAI (Python)** | [`narration-enrichment/`](./narration-enrichment/) | FastAPI + Instructor + Gemini + RAG + reliability |
| **Ticketing (microservices)** | [`ticketing-platform/`](./ticketing-platform/) | Java microservices, saga, Resilience4j, docker-compose |

## 🤖 For AI assistants (Claude, Codex, etc.)

**Start with [`AGENTS.md`](./AGENTS.md)** — the portable bootstrap that explains current state, working rules, teaching arc, and where the deep docs live. Machine-local memory doesn't survive a fresh clone; that file does.

## 📖 Roadmaps

- Ticketing: [`ticketing-platform/ROADMAP.md`](./ticketing-platform/ROADMAP.md)
- GenAI: [`Jarvis_GenAI_Path.md`](./Jarvis_GenAI_Path.md)
- Cross-track forward plan: [`NEXT_PATH.md`](./NEXT_PATH.md)

## 📚 Notes (per track)

- **Deep concept HTML** (companion to code) — `*_LAB.html` / `*_NOTES.html` in each track
- **Prose revision** with self-check questions — `LEARNING_NOTES.md` in each track
- **Study companion** (Q&A style) — `ticketing-platform/TICKET_STUDY.html`

## Standing conventions

- Hinglish comms · no `Co-Authored-By` trailer on commits · ask before push · learning-first mode · one-service-correctly before adding more · live verification over cherry-picked demos

See `AGENTS.md` §3 for the full rule set.
