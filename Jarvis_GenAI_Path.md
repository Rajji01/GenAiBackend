# Jarvis GenAI Backend Path

**Goal:** Java Backend Engineer → Production-grade GenAI Backend Engineer
**Anchor project:** Intelligent Transaction Platform (`github.com/Rajji01/GenAiBackend`)
**Operating model:** PROJECT → learn-what's-needed → build → test → deploy → observe → improve → next
**Stack rule:** Python-primary for learning depth (Instructor + Pydantic), Java/Spring AI for enterprise delivery. Port only P1 + P5 to Spring AI (structured output + tool calling = the dual-capability differentiator). Baaki har cheez do baar nahi.

---

## Assessment

**Moat (keep):** Java, Spring Boot, REST, JPA, SQL, testing, prod backend experience, basic AWS/DevOps.
**Gap (fill via projects):** LLM ke "andar" — structured output mechanism, embeddings + vector similarity, chunking + retrieval, prompt construction, hallucination/grounding, tool-calling loop, AI failure modes.
**Waste NOT:** NumPy/Pandas deep dive, ML theory, model training, backprop/math, DL course, separate Python course.

---

## Project Progression

| # | Project | New capability | Python/Java | AWS | Microservices | HLD focus |
|---|---------|----------------|-------------|-----|---------------|-----------|
| P1 | Transaction Enrichment API | Structured output | Python **+ Spring AI port** | — | Modular monolith | LLM-as-dependency, latency budget, retry/fallback |
| P2 | Transaction + policy RAG | Embeddings, retrieval, citations | Python | S3 (docs) | Modular monolith | RAG design: chunking, vector store, ranking |
| P3 | Knowledge assistant | Auth, memory, eval pipeline | Python | S3 | Modular monolith | Conversation memory, eval-as-a-system |
| P4 | Async doc-processing pipeline | Event-driven, idempotency, retries | Python | **SQS, S3, ECS/Lambda, CloudWatch** | **First real split: API + Worker** | Async HLD, DLQ, exactly-once vs at-least-once, backpressure |
| P5 | Tool-calling assistant | Tool loop + guardrails | Python **+ Spring AI port** | SQS | API + Worker | Tool-calling design, prompt-injection defence |
| P6 | Agentic workflow (dispute/recon) | Agent loop + "when NOT to agent" | Python | as needed | multi-service | Agent vs plain RAG decision, loop control |
| P7 | Multi-model platform | Routing, fallback, cost/latency, observability | Python | ECS/EKS, RDS+pgvector, Secrets Mgr, API GW, IAM | gateway + provider + retrieval services | Capacity + token-cost estimation, model routing |
| P8 | Capstone platform | Full prod system | both | Full stack + CI/CD | full | End-to-end system design |

---

## AWS Layer — kab, aur kyun

- **P1–P3:** AWS ki zaroorat nahi. Local + Docker + Compose. (P2/P3 mein docs ke liye **S3** = pehla touch.)
- **P4 = AWS ka asli ghar.** SQS (queue, DLQ, retries), S3, ECS-Fargate/Lambda (worker), CloudWatch (logs/metrics).
- **P7/P8 = full stack.** ECS/EKS, RDS (Postgres+pgvector), Secrets Manager (keys ab `.env` nahi), API Gateway, IAM least-privilege, CI/CD.

**Rule:** har service *use karke* seekhna, video dekhke nahi. 20-service list ratne mat baith.

---

## Microservices Layer — kab NAHI

- **P1–P3:** Modular monolith only (`api / service / llm / model / config`). Microservice ka naam bhi nahi.
- **P4:** Pehla genuine split — **API service** (queue mein daal ke turant return) + **Worker service** (embedding/LLM heavy kaam). Reason: embedding slow + spiky, API ko block nahi karna.
- **P7/P8:** Proper multi-service (gateway/routing, provider, retrieval).

**Interview line:** "Why not microservices from day 1?" → premature decomposition = distributed monolith, network latency + ops cost bina benefit ke; maine tab toda jab async workload ne independent scaling demand ki. (Zyada services = junior move.)

---

## HLD Layer — project-driven, continuous

Theoretically nahi padhna. Har project ek HLD artifact deta hai (README diagram + trade-off table) + interview Qs (pehle khud answer, phir correction).

- **P1:** structured output reliability, LLM dependency design, sync latency budget
- **P2:** "How do you design a RAG system?" (2026 ka top AI system-design Q)
- **P4:** async/event-driven HLD — idempotency, exactly-once vs at-least-once, DLQ, retry storms (classic senior HLD)
- **P7:** capacity + cost estimation — "10k req/day pe token cost? kaunsa model route? fallback?"

Complements LLD track (Strategy → Observer → Prototype → Decorator). LLD = code-level, HLD = system-level.

---

## WEEK 1 (P1) — ACTIVE

**Goal:** working `POST /enrich` → validated structured JSON. Local, tested, pushed.

**Build:** raw txn (merchant, amount, currency, raw description) → validated `EnrichedTransaction` (clean_merchant, category, is_subscription, confidence, human_narration).

**Concepts (sirf itne):** Instructor kaise Pydantic schema ko forced/validated JSON banata hai + retry; extraction prompt; malformed-output failure mode kyun real hai.

**Day plan:**
- Day 1: FastAPI skeleton + `/health`, Gemini key `.env` se, ek raw call chale
- Day 2: `EnrichedTransaction` Pydantic model + Instructor + pehla validated response
- Day 3: `POST /enrich` — request DTO, service layer, prompt, LLM-fail/timeout handling
- Day 4: failure modes — malformed retry samjho, timeout → clean 503, input validation
- Day 5: pytest — happy path (LLM mocked) + 1 validation-failure path, basic logging
- Weekend: README + `.env.example` + run instructions, commit + push

**Definition of Done:**
- [ ] `POST /enrich` schema-valid JSON on sample txns
- [ ] LLM fail/timeout pe clean error, no crash
- [ ] key env se, `.env.example` present
- [ ] happy-path + 1 failure test pass
- [ ] README with setup + example call (curl **PowerShell** mein, repo path quote karo)
- [ ] pushed to `GenAiBackend` (`enrichment-api/` folder)

DoD tick → LinkedIn GenAI claims green-light.

---

## Notes
- New job postings → share karo → `Jarvis_Roadmap.md` frequency analysis update
- Tool/model/version choices (P2 onwards) → current info web-verify tab
- Week N+1 tab tak nahi jab tak N ka DoD tick na ho
