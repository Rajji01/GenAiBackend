# interview-prep/ — the job-readiness hub

**Owner:** Rajat Agrawal · **Started:** 2026-10-25 · **Maintained by:** Jarvis each self-walk

This folder exists because of a direction Rajat set on **2026-10-25**:

> "ab ai specific chize jaise forward deployed engineer ya genai roles or interview
> preparations hld lld dsa ki preparation ache se krni hai — tu self walk to krta rah
> par ab mere project ko **real time soch, real time problems**." → "dono krna hai ache se."

Translation into a working rule: **the self-walk now has two jobs, not one** — and both
run every walk, neither gets dropped. See `AGENTS.md` §3 rule **§3-12** (the binding
version of this). This README is the operating manual + the index.

---

## The dual mandate (what every self-walk now does)

### Job A — advance + harden the project as a LIVE production system
Not just "next roadmap phase." Before picking a unit, ask the **prod-reality questions**:

- Ye cheez 3 baje raat ko kaise todegi? Kaun paged hoga, kya dashboard dekhega?
- Customer ka data **ganda** aaya to? (missing fields, wrong currency, 10× size, PDF scan)
- Scale/cost/latency ceiling kahan hai? Pehle kya phatega — DB, queue, token-budget, p99?
- Agar ye upstream (Gemini / SQS / DB) **down** ho jaaye — degrade ya die?

The Hardening arc (P5.5) was a one-time pass. **From 2026-10-25 that lens is permanent** —
every walk picks work that closes a *real prod gap*, not only a feature. "Real time soch,
real time problems" = this.

### Job B — mine the work for interview artifacts (4 pillars)
Every walk leaves **at least one concrete deposit** in this folder, in addition to its
project deposit. The four pillars, each its own file:

| Pillar | File | What it is |
|---|---|---|
| **FDE** — Forward Deployed Engineer | [`FDE.md`](FDE.md) | Customer-deployment framing of the platform — messy data, policy variance, SLA/cost, demo narrative, the FDE-specific interview shapes |
| **GenAI roles** | [`GENAI.md`](GENAI.md) | RAG / agentic / eval / multi-model depth in interview-Q shape. Cross-links to `NARRATION_STUDY.html`'s per-day Qs |
| **HLD + LLD** | [`HLD.md`](HLD.md) · [`LLD.md`](LLD.md) | System-design walkthroughs (per phase) + design-pattern catalog mapped to real code in this repo |
| **DSA** | [`dsa/`](dsa/) | Algorithmic prep — pattern-wise, solved problems + notes. The one pillar that does NOT come from the project, so it runs as its own thread |

**Rotation rule:** don't hammer one pillar. Across consecutive walks, touch all four so
none goes stale. A walk's deposit can be small (one scenario, one walkthrough, one pattern
entry, one solved DSA problem) — rule §3-11's "small is fine" applies here too.

---

## How this folder relates to what already exists

This does **not** replace the per-track study files — it sits above them:

- `narration-enrichment/NARRATION_STUDY.html` + `ticketing-platform/TICKET_STUDY.html`
  = **per-day, per-track** interview Qs (rule §3-11). Granular, tied to one commit.
- **`interview-prep/`** = **cross-track, role-shaped** prep. An interviewer doesn't ask
  "P4 Day 3" — they ask "design an async pipeline" / "deploy this for our customer" /
  "reverse a linked list." This folder is organised by *how the question gets asked*.

When a pillar file would just duplicate a STUDY entry, **link to it** instead of copying
(no fragmentation — rule §3-7).

---

## Status snapshot (keep current)

| Pillar | Seeded | Depth | Last touched |
|---|---|---|---|
| FDE | ✅ scaffold + 2 scenarios | thin | 2026-10-25 |
| GenAI | ✅ scaffold + topic map + LangChain Rosetta | thin (links STUDY) | 2026-10-25 |
| HLD | ✅ scaffold + 2 walkthroughs (RAG + 10×-traffic) | thin | 2026-10-25 |
| LLD | ✅ scaffold + pattern catalog | thin | 2026-10-25 |
| DSA | ✅ plan + pattern list | empty (no problems solved yet) | 2026-10-25 |

The project itself is the evidence base: narration P1–P7 + Hardening (360 tests),
ticketing Weeks 1–4. Full state in `AGENTS.md` §4.
