# District Ticketing Platform — Architect Roadmap

> **Kya hai ye:** BookMyShow/District-style event ticketing system ko ek microservice se lekar
> FANG-level HLD + production-ready AWS tak le jaane ka complete roadmap.
> **Kiske liye:** Java backend engineer (~6.5 yrs) → Solutions Architect prep.
> **Goal:** Java + Spring Boot + Microservices + AWS + LLD + HLD + Production Engineering — theory nahi,
> ek real distributed system *design, implement, deploy, secure, monitor aur debug* karke.

---

## Status

| | |
|---|---|
| **Week 1** | ✅ DONE — `inventory-service` prod-grade (local) |
| **Current** | Week 2 ready to start |
| **Domain** | Event ticketing (District / BookMyShow clone) |
| **Soul of the system** | Flash-sale mein bhi *correct* booking — no oversell, no crash, no lost money |

**Week 1 recap (already built):** ek Spring Boot `inventory-service` — Postgres (durable source of truth)
+ Redis (ephemeral TTL holds), two-tier concurrency defense (Redis `SETNX` + Postgres `@Version`),
saga-style compensating actions, self-healing reconciliation sweep, 41 tests on real containers
(Testcontainers, no fakes). Core problem solved: **oversell prevention**.

---

## Table of Contents

1. [Target end-state architecture](#1-target-end-state-architecture)
2. [The Path — macro progression](#2-the-path--macro-progression)
3. [Phase-by-phase detail](#3-phase-by-phase-detail)
4. [Weekly arc](#4-weekly-arc)
5. [Daily rhythm template](#5-daily-rhythm-template)
6. [Week 2 — detailed daily plan](#6-week-2--detailed-daily-plan)
7. [The 8-question AWS framework](#7-the-8-question-aws-framework)
8. [How to use this file](#8-how-to-use-this-file)

---

## 1. Target end-state architecture

Ye final system hai jise build karna hai. Har box ek **genuine business capability** hai —
"service exist karti hai isliye" nahi.

```
                          ┌─────────────┐
              Client ────►│  CloudFront │  (catalog static + CDN)
                          └──────┬──────┘
                                 ▼
                          ┌─────────────┐    ┌──────────┐
                          │ API Gateway │◄───│  Cognito │ (auth / JWT)
                          │   + WAF     │    └──────────┘
                          └──────┬──────┘
                                 ▼  (ALB → ECS Fargate)
        ┌────────────┬───────────┼────────────┬──────────────┐
        ▼            ▼           ▼            ▼              ▼
  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐
  │ catalog  │ │inventory │ │ booking  │ │ payment  │ │ notification │
  │ (read-   │ │(seats/   │ │(SAGA     │ │(gateway +│ │ (fan-out     │
  │  heavy)  │ │ holds) ✅│ │ orch.)   │ │ webhook) │ │  consumer)   │
  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘ └──────┬───────┘
       │            │            │            │              │
    Aurora      RDS + Redis   RDS + Outbox  RDS/Dynamo    (consumes)
    + Redis     (ElastiCache)    │
                                 ▼
                     ┌────────────────────────┐
                     │ EventBridge / SNS→SQS  │  ◄── event backbone
                     └───────────┬────────────┘
                                 ▼
                     ┌────────────────────────┐
                     │ analytics (Kinesis→S3  │
                     │ → Athena) + Lambda     │
                     └────────────────────────┘

  Cross-cutting: CloudWatch + X-Ray tracing, Secrets Manager, KMS,
  Terraform (IaC), GitHub Actions → ECR → ECS (CI/CD), DLQs everywhere.
```

**Services (7):** catalog, inventory (✅ done), booking, payment, notification, analytics,
+ identity (mostly Cognito). Sab progressively add honge — jab genuine zaroorat aayegi.

**Why this domain:** Ticketing ka *the* HLD problem hai the **flash sale** — 50,000 log ek Coldplay/Diljit
show pe ek saath toot padte hain. Tab bhi:
(a) koi seat double-book na ho, (b) system crash na ho, (c) paisa kate to ticket mile / na mile to refund ho,
(d) har user ko clean response mile. Pura roadmap isi ek problem ke around bana hai.

---

## 2. The Path — macro progression

| Phase | Weeks | Ek-line goal | New services | Core HLD problem | New AWS |
|-------|-------|--------------|--------------|------------------|---------|
| **1. Distributed Core** | 2–3 | 2 services baat karein, booking saga bane | booking, payment | Saga orchestration, cross-service idempotency, outbox | — (local) |
| **2. First AWS Landing** | 4–5 | System real AWS pe chale, sync→async | — | Managed infra, async decoupling | IAM, VPC, RDS, ECR, ECS Fargate, ALB, Secrets Mgr, SQS, SNS, DLQ |
| **3. Event-driven maturity** | 6–7 | Fan-out events + read-heavy catalog | catalog, notification | Pub/sub fan-out, CQRS-lite, caching, eventual consistency | EventBridge, ElastiCache, CloudFront, Aurora |
| **4. Scale & Flash-Sale** | 8–9 | 50k concurrent users survive | — | Virtual waiting room, load-leveling, rate limit, NoSQL-at-scale | DynamoDB, autoscaling, API GW throttling |
| **5. Security hardening** | 10 | Kaun kya access kar sakta — verify | identity | AuthN/AuthZ, bot/scalper defense, least privilege | Cognito, WAF, KMS, IAM roles |
| **6. Observability** | 11 | "Booking slow kyun hua" 2 min mein pata chale | — | Distributed tracing, correlation, alerting | CloudWatch, X-Ray/ADOT, alarms |
| **7. CI/CD + IaC** | 12 | Ek push → prod, ek command → poora env | — | Reproducibility, safe deploys, rollback | Terraform, CodePipeline/GH Actions, blue-green |
| **8. Serverless + Analytics** | 13 | Sahi jagah Lambda, event analytics pipeline | analytics | When serverless wins, stream processing | Lambda, Kinesis, S3, Athena |
| **9. Production Hardening** | 14 | Kuch bhi toote to system zinda rahe | — | Chaos, DR, multi-AZ, cost | Multi-AZ, backups, cost tools |
| **10. GenAI Layer** | 15+ | System ke upar AI (long-term goal) | ai-service | Semantic search, RAG support agent | Bedrock / OpenSearch (+ Claude/LangChain stack) |

**Golden rule:** har naya AWS service introduce hote waqt 8 questions cover karo (see [section 7](#7-the-8-question-aws-framework)).

---

## 3. Phase-by-phase detail

### Phase 1 — Distributed Core (Weeks 2–3) — *sabse important HLD phase*

Ek service se multi-service architecture. Yahi woh moment hai jahan asli distributed complexity shuru hoti hai —
architect interviews ke ~60% questions isi phase se.

- **Naye services:** `booking-service` (saga orchestrator — system ka dimaag), `payment-service` (abhi stub gateway).
- **HLD problems:**
  - **Saga pattern** — booking = hold seat (inventory) + charge (payment) + confirm = distributed transaction.
    2PC kyun nahi (blocking, coordinator SPOF). Orchestration (booking coordinate kare) vs choreography
    (services aapas mein events se). Hum **orchestration** chunenge — kyun likh ke rakhna.
  - **Compensating transactions** — payment fail → seat release. (Week 1 mein chhoti scale pe kiya tha; ab
    service-boundary ke paar.)
  - **Idempotency across services** — client `Idempotency-Key` bhejega; network retry pe double booking na ho.
  - **Outbox pattern** — booking + event dono ek DB transaction mein likho, poller publish kare. Dual-write
    problem solve. (Week 1 mein deliberately nahi tha — ab neenv.)
  - **Dangling saga recovery** — booking crash jab seat HELD tha but CONFIRMED nahi. Kaun clean karega?
    (Reconciliation ka distributed version.)
- **LLD:** booking **state machine** (State pattern vs enum+switch — kab worth), **Command pattern** for saga
  steps (execute/compensate), **Strategy** for payment methods (UPI/Card/NetBanking).
- **AWS:** abhi zero (deliberate). Pehle distributed problem local (docker-compose) pe feel karo, phir AWS —
  warna AWS-debugging + distributed-logic-debugging ek saath = chaos.
- **Analogy:** Zomato order — restaurant accept (inventory) → payment → delivery assign (confirm). Koi step
  fail → gracefully rollback/retry. Saga exactly yahi.

### Phase 2 — First AWS Landing (Weeks 4–5)

2–3 service ka system real AWS pe, aur sync coupling ko async mein todo.

- **Week 4 — infra foundation:** IAM (roles, least privilege, *no hardcoded creds*), VPC (public/private subnets,
  NAT, security groups), RDS Postgres (Multi-AZ), Secrets Manager (DB creds), ECR, ECS Fargate, ALB.
  Deploy inventory + booking.
- **Week 5 — async decoupling:** SQS, SNS, DLQ, visibility timeout, redrive. booking→notification ko async.
  Outbox rows ab SQS mein.
- **Key decision to justify:** ECS Fargate vs EC2 vs Lambda — inventory/booking ke liye Fargate kyun.

### Phase 3 — Event-driven maturity (Weeks 6–7)

- **notification-service** — SNS→SQS fan-out (`BookingConfirmed` → email + SMS + push parallel).
  **EventBridge** for routing + schema registry.
- **catalog-service** — read-heavy (10,000 reads : 1 write). **ElastiCache caching**, **CloudFront CDN**,
  **Aurora read replicas**, **eventual consistency** (catalog ka "seats available" count eventually consistent;
  real truth inventory ke paas). **CQRS-lite** intro.
- **Analogy:** BookMyShow home page (catalog) crash nahi hona chahiye chahe booking busy ho — read/write
  alag scale.

### Phase 4 — Scale & Flash-Sale (Weeks 8–9) — *the crown jewel*

System ko "toy" se "real ticketing" banata hai. Coldplay/Diljit ticket-drop scenario.

- **Virtual waiting room** — 50k log ek saath → sab andar mat aane do; queue + token + controlled release.
- **Queue-based load leveling** — spike SQS absorb kare, backend apni speed pe process (backpressure).
- **Rate limiting / throttling** — API Gateway usage plans, token bucket.
- **DynamoDB** — idempotency table (TTL auto-cleanup — no reconciliation sweep!) + high-write booking log.
  DynamoDB *kyun* Postgres ke bajaye (predictable single-digit ms at any scale, partition-key design).
- **Autoscaling** — ECS target tracking.

### Phase 5 — Security (Week 10)

Cognito (user auth, JWT), WAF (scalper/bot defense — ticketing ka real problem), KMS (encryption at rest/transit),
fine-grained IAM. "Kaun kya access kar sakta, aur AWS verify kaise karta."

### Phase 6 — Observability (Week 11)

`CorrelationIdFilter` ab distributed. CloudWatch metrics/alarms/composite alarms, **X-Ray ya ADOT
(OpenTelemetry)** distributed tracing — poore saga ka ek trace (booking→inventory→payment).
Scenario: *"Booking API slow, latency kahan?"* → trace se pinpoint.

### Phase 7 — CI/CD + IaC (Week 12)

**Terraform** — poora env ek command se destroy + recreate. GitHub Actions → test → Docker build → ECR →
ECS deploy → health check → blue/green + rollback.

### Phase 8 — Serverless + Analytics (Week 13)

**Lambda** jahan woh actually jeette — hold-expiry (scheduled), payment webhook, image processing.
**Kinesis → S3 → Athena** analytics pipeline. "Serverless kab win karta" ka honest answer.

### Phase 9 — Production Hardening (Week 14)

Failure-first chaos: AZ down, DynamoDB throttle, Redis down, ECS task crash. Har ek ke liye
**Detection → Impact → Recovery → Prevention**. Cost optimization, DR, backups.

### Phase 10 — GenAI Layer (Weeks 15+) — *long-term goal*

System ke upar AI: catalog **semantic search** ("family-friendly comedy near me this weekend"),
**RAG support agent** (booking/refund queries), aur **ArchMaster** iss real system ko case-study bana ke use kare.
Claude/LangChain stack yahan plug.

---

## 4. Weekly arc

| Week | Goal |
|------|------|
| 1 ✅ | inventory-service prod-grade local (DONE) |
| 2 | booking-service + saga orchestration (sync), cross-service idempotency |
| 3 | payment-service stub + outbox pattern + saga rollback + dangling recovery |
| 4 | AWS foundation (IAM/VPC/RDS/ECR/ECS Fargate/ALB) — 2 services live |
| 5 | SQS/SNS/DLQ — sync→async decoupling |
| 6 | notification-service + SNS fan-out + EventBridge |
| 7 | catalog-service + ElastiCache + CloudFront + eventual consistency |
| 8 | Flash-sale: virtual waiting room + load-leveling + rate limiting |
| 9 | DynamoDB (idempotency + booking log) + autoscaling |
| 10 | Cognito + WAF + KMS + least-privilege IAM |
| 11 | CloudWatch + X-Ray tracing + alarms |
| 12 | Terraform + CI/CD + blue-green + rollback |
| 13 | Lambda + Kinesis→S3→Athena analytics |
| 14 | Chaos + DR + cost + production hardening |
| 15+ | GenAI: semantic search + RAG agent + ArchMaster tie-in |

---

## 5. Daily rhythm template

Har week isi rhythm pe chalega (realistic scope: 2–3 focused hours/day):

- **Day 1 — Design:** mental model + dry-run trace + LLD/HLD decisions + API contract. **Zero code.**
- **Day 2–3 — Implement:** Spring Boot code + tests.
- **Day 4 — AWS/Integration:** deploy ya wire-up (early weeks local, Phase 2+ real AWS).
- **Day 5 — Failure experiment:** ek cheez jaan-bujh ke todo, dekho, fix karo.
- **Weekend — Review + LLD + Interview:** architecture review, LLD Q&A, interview questions
  (answer pehle, evaluate baad mein), Definition of Done check, notes.

---

## 6. Week 2 — detailed daily plan

**Goal:** `booking-service` khada karo jo saga orchestrator ho — inventory ko call kare (sync REST pehle),
booking state machine chale, idempotency service-boundary ke paar kaam kare.
**Abhi local (docker-compose), koi AWS nahi.**

- **AWS services:** none (deliberate).
- **Domain capability:** "user ek booking initiate karta hai jo seat hold + payment coordinate karti hai."

### Day 1 — Design (no code)
- Booking **state machine**: `PENDING → SEATS_HELD → PAYMENT_INITIATED → CONFIRMED` (+ `FAILED`, `EXPIRED`).
  Har transition ka trigger + invalid transitions block (e.g. `EXPIRED→CONFIRMED`).
- Service boundaries: booking-service = booking aggregate owner; seats = inventory ke. booking sirf inventory ke
  `/hold` + `/confirm` call kare, seat directly touch na kare.
- **Saga: orchestration** decide karo — booking central coordinator. Choreography kyun nahi (abhi) — likho.
- Idempotency-Key: client header → `bookings` table pe unique constraint → dup = same booking return.
- API contract: `POST /bookings` (showId, seatIds, holderId, Idempotency-Key) → 201; `GET /bookings/{id}`.
- **Deliverable:** diagram + state-transition table + API contract. Code nahi.

### Day 2 — Build (skeleton + persistence)
- `booking-service` Spring Boot 3.4 / Java 17, apna Postgres schema (database-per-service).
- `Booking` entity + `BookingStatus` enum + `@Version` + `idempotency_key` unique.
- `BookingController` (`POST`, `GET`) + DTOs + reuse `GlobalExceptionHandler` + `CorrelationIdFilter`.
- Idempotency store: dup key → existing booking return (naya insert nahi).

### Day 3 — Build (saga happy path)
- `InventoryClient` (Spring `RestClient`) → inventory `/hold` + `/confirm`.
- Orchestrator: `PENDING` → hold → `SEATS_HELD` → payment stub success → confirm → `CONFIRMED`.
- **Resilience4j:** timeout + retry + circuit breaker on `InventoryClient`.
- **Correlation ID propagation:** `X-Correlation-Id` booking→inventory forward — ek booking, ek ID, dono logs.

### Day 4 — Local integration
- booking-service ko `docker-compose` mein (inventory + booking + dono Postgres + Redis).
- E2E curl: `POST /bookings` → dono DB verify (inventory seat `BOOKED`, booking `CONFIRMED`).
- Do parallel bookings same seat → ek jeete, ek clean fail (Week 1 guarantee ab service ke through).

### Day 5 — Failure experiments (min 2)
1. **inventory down mid-saga** → booking hang na ho; timeout → `FAILED`; kuch held nahi to compensate nahi.
2. **hold OK but payment fail** → compensating action: inventory `/release` → seat `AVAILABLE`, booking `FAILED`.
   (Saga rollback — Day 5 ka star.)
3. **confirm response lost** → same Idempotency-Key retry → same `CONFIRMED`, no double-book.

### Weekend — Review + LLD + Interview
- **LLD deep-dive:** State pattern vs enum+switch (kab worth?); Command pattern for saga steps
  (execute + compensate) — dry run.
- **Interview questions** (interviewer poochega, tu answer, phir evaluate — answer pehle mat dekho):
  1. Booking flow ke liye orchestration vs choreography saga — kaunsa aur *kyun*?
  2. Seat hold ho gaya but payment fail — exactly kya compensate, aur agar compensation *bhi* fail?
  3. Idempotency-Key kahan store, kab tak valid, uniqueness kis field pe?
  4. booking crash — seat HELD, CONFIRMED nahi. Recovery strategy? (dangling saga)
  5. Sync REST booking→inventory ka core problem? Async kab justify?
  6. 2PC kyun avoid ticketing mein?
  7. `EXPIRED` booking ko `CONFIRMED` hone se kaise roko — kis layer pe?

### Definition of Done
- [ ] booking-service compose mein chalta hai, apna DB
- [ ] `POST /bookings` happy path E2E works
- [ ] Idempotency: dup request = 1 booking
- [ ] Saga rollback: payment fail → seat released
- [ ] Timeout + circuit breaker on inventory client
- [ ] Correlation ID dono services mein flow karti hai
- [ ] Tests (Testcontainers): controller slice + 1 E2E saga test + 1 rollback test

> **Week 3 tab shuru** jab ye DoD tick ho jaye. Progressive complexity — ek week at a time.

---

## 7. The 8-question AWS framework

Har naya AWS service introduce hote waqt ye 8 answer karo (answer khud pehle, mentor evaluate baad mein):

1. **WHY?** — Is application ko iski zaroorat kyun?
2. **WHAT?** — Service kya provide karti hai?
3. **HOW?** — Spring Boot ke saath integrate kaise?
4. **TRADE-OFF?** — Kaun se alternatives the?
5. **FAILURE?** — Fail ho gayi to kya hota hai?
6. **SCALE?** — Load badhne pe kaise behave karti hai?
7. **SECURITY?** — Secure kaise karein?
8. **COST?** — Cost kya drive karta hai?

**Never** koi AWS service sirf isliye add karo ki woh exist karti hai. Requirement → Architecture problem →
Service selection → Implementation → Deployment → Failure test → Optimization → Interview question.

---

## 8. How to use this file

- Ye **living document** hai — har week complete hone pe weekly arc mein ✅ mark karo aur us week ka detailed
  daily plan (Week 2 jaisa) add karte jao.
- Repo mein `ROADMAP.md` ke naam se root pe rakho.
- Har phase ke end pe ek **Architecture Review** section add karo: What's good / What's weak /
  What would break in production / What a Staff Engineer would change.
- Final goal: ye repo aur README itne strong ho ki dekhne wale ko lage tumne AWS architecture *samjhi* hai,
  tutorial follow nahi kiya.

---

*Roadmap version 1.0 — Phase 1 se pehle. Progressively evolve karega.*
