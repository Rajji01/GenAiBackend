# Jarvis OpenAI Context Memo

> Persistent working context for collaborating on this repository. Update this
> only when Rajat explicitly permits a change, or asks to record progress.

## Communication and working agreement

- Talk in Hinglish; user calls the assistant "Jarvis" / "bhai".
- Before any tool action, say plainly what will be read, changed, run, or
  searched, and why. Do not make the user guess what permission is being used.
- Read-only work needs read permission. Never create, edit, delete, run tests,
  start Docker, call external services, or make Git changes without clear user
  permission for that specific type of action.
- Maintain this memo as progress evolves, but ask/receive permission before
  editing it.
- Learning style: project-first and evidence-first. Learn a concept when the
  project needs it; build it, test it, run it where meaningful, document the
  trade-off and any real failure, then move on.

## North-star goal

**Java Backend Engineer -> Production-grade GenAI Backend Engineer -> AI
Architect.**

The goal is not generic ML study. Build the ability to design and deliver
reliable production GenAI systems with Java/Spring AI for enterprise delivery
and Python for fast, deep understanding of GenAI mechanics.

## Deliberate scope boundaries

- Keep and compound: Java, Spring Boot, REST, JPA, SQL, testing, backend
  reliability, basic AWS/DevOps.
- Fill through projects: structured LLM output, embeddings/vector similarity,
  chunking/retrieval, grounded prompting, hallucination control, tool loops,
  evaluation, model/provider failures, cost/latency and observability.
- Do **not** spend roadmap time on ML model training, backprop/DL theory, or a
  separate broad Python course.
- Python is primary for GenAI learning depth. Port only P1 and P5 to Spring AI
  (structured output and tool calling); do not duplicate every project.
- Avoid premature microservices. P1-P3 remain modular monoliths. Split only at
  P4 when asynchronous LLM/embedding work needs independent scaling.

## Master GenAI project roadmap

| Project | Focus | Platform / architecture |
|---|---|---|
| P1 - Transaction Enrichment API | Structured output, LLM reliability | Python + Spring AI port; modular monolith |
| P2 - Transaction + policy RAG | Documents, chunking, retrieval, citations | Python; S3; modular monolith |
| P3 - Knowledge assistant | Auth, memory, evaluation pipeline | Python; S3; modular monolith |
| P4 - Async document processing | Events, idempotency, retries, backpressure | API + worker; SQS, S3, ECS/Lambda, CloudWatch, DLQ |
| P5 - Tool-calling assistant | Tool loop and guardrails | Python + Spring AI port; API + worker |
| P6 - Agentic dispute/reconciliation workflow | Agent-loop decisions and loop controls | Multi-service as justified |
| P7 - Multi-model platform | Routing, fallback, cost/latency, observability | ECS/EKS, RDS + pgvector, Secrets Manager, API Gateway, IAM |
| P8 - Capstone platform | Full production system | Both languages; CI/CD and full architecture |

### Architecture-learning checkpoints

- P1: LLM as dependency, structured-output reliability, synchronous latency
  budget, retries/fallback.
- P2: RAG design: document ingestion, chunking, retrieval/ranking, citations.
- P4: async HLD, at-least-once delivery, idempotency, DLQ, retry storms,
  backpressure. This is the first valid microservice split.
- P7: capacity and token-cost estimation, routing and provider fallback.

## Current progress

### Java backend foundation (`backend/`)

UFC/betting backend establishes the Java baseline:

- Spring Boot 3, REST, JPA/Hibernate, MySQL, Flyway schema ownership
  (`ddl-auto=validate`), DTO boundaries, Bean Validation, centralized RFC 7807
  errors, SLF4J logging, env-driven config, constructor injection and Swagger.
- Test pyramid used deliberately: Mockito unit tests, `@WebMvcTest` slices,
  full Spring integration tests.
- Applied `@Version` optimistic locking to a real `Bet` flow; lost updates were
  proven through stale-read, true concurrent-thread, and live HTTP tests.
- Detailed rationale and self-checks are in `backend/LEARNING_NOTES.md` and
  `backend/CORNER_NOTES.html`.

### P1 - Narration Enrichment (`narration-enrichment/`)

P1 is completed far beyond its initial Week 1 definition:

- FastAPI service turns messy bank transaction narrations into typed
  `TransactionEnrichment` results.
- Raw Gemini experiments deliberately reproduced bad JSON/fences/type-shape
  failures; Pydantic plus Instructor/native tool calling now validates the
  boundary instead of trusting model prose.
- Request validation, provider HTTP timeout, type-based error mapping,
  PII-aware logging, correlation IDs and Docker health checks are implemented.
- Evaluation uses a golden dataset and separates correctness from call failure.
- Batch isolation, SQLite persistence, stats, selective retries for observed
  transient provider errors, and an in-process quota limiter are implemented.
- RAG reuses persisted enrichment history: document/query embeddings, cosine
  similarity, top-k context and graceful degradation if embedding fails.
- Important real findings are documented: Instructor exception wrapping,
  logging-filter placement, SQLite in-memory pooling, and measured free-tier
  rate limits.
- Tests are mocked at HTTP/LLM boundaries where appropriate; real calls were
  used only to validate claims that require model behavior.

### Ticketing system-design track (`ticketing-platform/`)

Phase 0 / Week 1 `inventory-service` is complete and is a companion
concurrency/system-design track:

- District/BookMyShow-style seat availability and holds.
- Redis `SETNX` + TTL gives fast expiring mutual exclusion; Postgres `@Version`
  remains the durable correctness safety net.
- Holds and releases are designed to be idempotent; compensation removes a
  Redis lock if the durable step fails.
- Scheduled reconciliation converts a Redis-expired `HELD` seat back to
  `AVAILABLE`; polling was chosen for self-healing over lossy pub/sub events.
- Global errors, correlation IDs/MDC cleanup, configuration properties,
  Actuator, Docker Compose and Testcontainers are present.
- Same-seat competition was proven in automated real-container tests and with
  live parallel HTTP calls: exactly one 200, one 409, no oversell.
- This track is especially useful preparation for P4's event-driven,
  idempotent and failure-handling design.

## Key sources in this repository

- `Jarvis_GenAI_Path.md` - master roadmap and scope rules.
- `narration-enrichment/README.md` and `LEARNING_NOTES.md` - P1 decisions,
  week-by-week discoveries and validation evidence.
- `ticketing-platform/README.md` - inventory-service design and Week 1 record.
- `backend/LEARNING_NOTES.md` and `CORNER_NOTES.html` - Java backend foundation.

## Current next-step orientation

The next planned GenAI evolution after the completed P1 work is P2: expand
from transaction-history RAG into document/policy RAG with a deliberate
ingestion, chunking, retrieval, ranking and citation design. Do not add AWS or
microservices merely for keywords; P4 is where SQS/DLQ/API-worker separation
becomes architecturally justified.

