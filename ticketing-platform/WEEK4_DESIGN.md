# Week 4, Day 1 — AWS foundation DESIGN (no code, no resources)

> **Scope of THIS file:** the design + the plan only. Per standing rule §3-2,
> **Rajat creates every real AWS resource** ("bs aws services mai banaunga").
> Claude pairs on the design, the Terraform, and verification — Claude never
> runs `terraform apply` or clicks "Create" in the console. Every step below
> is tagged **[Rajat]** (you provision) or **[Claude]** (I author/verify) so
> the boundary is never ambiguous.
>
> **Roadmap anchor:** `ROADMAP.md` Phase 2 (Weeks 4–5), Week 4 = infra
> foundation. Goal: take the two already-built services (`inventory-service`,
> `booking-service`) from local docker-compose to a real AWS landing, still
> synchronous (async SQS/SNS is Week 5). `payment-service` +
> `notification-service` follow once the two-service shape is proven.
>
> **The one rule for every AWS service introduced:** answer the 8 questions
> (`ROADMAP.md` §7) — WHY / WHAT / HOW / TRADE-OFF / FAILURE / SCALE /
> SECURITY / COST — *before* it goes in. This paper does that for each.

---

## 0. What actually changes from Week 3

Nothing in the application code changes for Week 4 — that's the point. The
services are already 12-factor enough (config from env, stateless, own DB,
healthcheck endpoint) that "landing on AWS" is an *infrastructure* exercise,
not a rewrite. What changes:

| Concern | Week 3 (local) | Week 4 (AWS) |
|---|---|---|
| Runtime | `./mvnw spring-boot:run` on host | ECS Fargate task (container) |
| Image registry | local Docker daemon | **ECR** |
| Database | Postgres in docker-compose | **RDS Postgres** (Multi-AZ) |
| DB credentials | `.env` file | **Secrets Manager** → injected into task |
| Network | localhost | **VPC** (public/private subnets, SGs, NAT) |
| Entry point | `localhost:8081/8082` | **ALB** (one DNS name, path/host routing) |
| Identity | none | **IAM** task roles (least privilege) |
| Reproducibility | compose file | **Terraform** (IaC) |

Deliberate non-goals for Week 4 (they belong to later phases, don't sneak
them in): SQS/SNS async (Week 5), CloudFront/ElastiCache (Phase 3),
autoscaling + DynamoDB (Phase 4), Cognito/WAF (Phase 5), CI/CD pipeline
(Phase 7). Week 4 is "it runs on managed AWS infra, reproducibly, securely."

---

## 1. Target Week-4 topology

```
                          Internet
                             │
                             ▼
                   ┌───────────────────┐
                   │  ALB (public)     │  DNS: ticketing-alb-*.elb.amazonaws.com
                   │  :80  (HTTPS→P5)  │  listener rules route by path:
                   └─────────┬─────────┘   /api/inventory/*  → inventory TG
                             │              /api/booking/*    → booking TG
        ┌────────────────────┼────────────────────┐
        ▼ (private subnets)  ▼                     ▼
  ┌──────────────┐   ┌──────────────┐        health checks
  │ ECS Fargate  │   │ ECS Fargate  │        /actuator/health
  │ inventory    │   │ booking      │
  │ task (:8081) │   │ task (:8082) │
  └──────┬───────┘   └──────┬───────┘
         │ booking → inventory over the ALB's INTERNAL path (or service
         │ discovery); NOT localhost anymore — this is the first real
         │ "service can't find service" failure surface
         ▼                   ▼
  ┌───────────────────────────────────┐        ┌──────────────────┐
  │ RDS Postgres (Multi-AZ)           │◄───────│ Secrets Manager  │
  │ databases: inventory, booking     │  creds │ db master + app  │
  └───────────────────────────────────┘        └──────────────────┘
         ▲
         │ private subnets, no public IP; NAT GW for egress (ECR pull, etc.)

  Cross-cutting: IAM task roles (least-priv), ECR (images), CloudWatch
  Logs (task stdout → log group), Terraform (all of the above as code).
```

**Subnet math:** 2 AZs × (1 public + 1 private) = 4 subnets. Public holds the
ALB + NAT GW; private holds ECS tasks + RDS. RDS never gets a public IP.

---

## 2. The 8-question pass, per service

### 2.1 VPC + networking

- **WHY:** isolation + the security boundary. Tasks and DB must not be
  publicly reachable; only the ALB is. Without a VPC you either expose the DB
  to the internet or you have no private/public split at all.
- **WHAT:** a logically isolated network — subnets (public/private across 2
  AZs), route tables, an internet gateway (public egress/ingress), a NAT
  gateway (private→internet egress only, e.g. ECR/Secrets pulls), security
  groups (stateful virtual firewalls).
- **HOW:** ECS tasks run in private subnets with `assignPublicIp=DISABLED`;
  the ALB sits in public subnets; RDS in a DB subnet group over the private
  subnets. **[Claude]** authors the Terraform `vpc` module; **[Rajat]**
  applies it.
- **TRADE-OFF:** default VPC (zero setup, but everything's public and flat) vs
  a purpose-built VPC (more Terraform, correct boundaries). We build our own —
  the whole Phase-2 point is understanding the boundary, not hiding it.
- **FAILURE:** one NAT GW = single AZ egress SPOF; if that AZ dies, private
  tasks in the *other* AZ lose egress. Week-4 accepts one NAT GW for cost;
  documented as a known compromise (prod = one NAT per AZ). An SG misrule is
  the more likely failure — the Day-5 experiment probes exactly this.
- **SCALE:** subnets sized with room (e.g. /24 each) so task/ENI count can
  grow; VPC itself doesn't "scale," its CIDR is the ceiling — pick generously
  (/16).
- **SECURITY:** the star of Week 4. SG rules are least-open: ALB SG allows
  :80 from world; ECS SG allows the app port **only from the ALB SG** (not
  CIDR); RDS SG allows :5432 **only from the ECS SG**. Reference SGs by id,
  never by CIDR — that's the "who, not where" model.
- **COST:** VPC/subnets/SG/IGW are free; **NAT GW is the line item** (~hourly
  + per-GB). Interface/Gateway VPC endpoints (S3, ECR, Secrets) can cut NAT
  data cost later; Week 4 keeps it simple, notes the optimization.

### 2.2 IAM

- **WHY:** no hardcoded credentials, anywhere. A task that needs to read a
  secret or pull an image proves its identity via a role, not an access key.
- **WHAT:** roles + policies. Two distinct ECS roles: the **task execution
  role** (used by the ECS agent to pull the ECR image + read the secret at
  start) and the **task role** (the app's own runtime identity — what the
  Java process can call). Least privilege on both.
- **HOW:** **[Claude]** writes the policy JSON (scoped to *this* repo's ECR
  repo ARN + *these* secret ARNs, not `*`); **[Rajat]** creates the roles.
- **TRADE-OFF:** one fat role for everything (easy, over-permissioned) vs
  execution/task split (correct, least-priv). We split — it's the interview-
  signature distinction.
- **FAILURE:** a too-narrow policy = task won't start (can't pull image /
  can't read secret) — visible immediately in ECS events, easy to widen. A
  too-wide policy is the silent danger; audit against the two ARNs.
- **SCALE:** roles are free and don't scale-limit anything.
- **SECURITY:** the entire reason IAM exists here. Rule: policies name exact
  resource ARNs; no `Resource: "*"` on the app roles.
- **COST:** free.

### 2.3 ECR

- **WHY:** ECS Fargate pulls images from a registry; the local Docker daemon
  isn't reachable from AWS. ECR is the AWS-native private registry.
- **WHAT:** a private Docker image registry, one repo per service
  (`ticketing/inventory-service`, `ticketing/booking-service`).
- **HOW:** **[Rajat]** `aws ecr get-login-password | docker login`, then
  `docker build` + `docker push` the existing per-service Dockerfiles.
  **[Claude]** provides the exact build/tag/push command sequence + a note on
  immutable tags (git SHA, not `latest`).
- **TRADE-OFF:** Docker Hub (public, rate-limited, external) vs ECR (private,
  IAM-gated, same-region low-latency pull). ECR — it's inside the trust
  boundary and pulls faster into ECS.
- **FAILURE:** wrong-arch image (building on an ARM Mac, running on x86
  Fargate) = task boot loop. Note: build `--platform linux/amd64` (or set
  Fargate to ARM64). This is a real gotcha to call out before the first push.
- **SCALE:** ECR scales transparently; lifecycle policy prunes old tags.
- **SECURITY:** repo policy + scan-on-push (free basic scanning) for CVEs.
- **COST:** storage per GB-month + data transfer (free within same region to
  ECS). Lifecycle policy keeps it small.

### 2.4 ECS Fargate — *the headline decision*

- **WHY:** we need to run containers without managing servers. Fargate =
  serverless containers (no EC2 to patch/scale/right-size).
- **WHAT:** ECS = the orchestrator (task definitions, services, desired
  count, health-based replacement). Fargate = the launch type where AWS runs
  the container on capacity you never see.
- **HOW:** a **task definition** per service (image, cpu/mem, port,
  secrets→env mapping, log config) + an **ECS service** (desired count 2,
  registered with an ALB target group, rolling deploy). **[Claude]** writes
  the task-def JSON/Terraform; **[Rajat]** creates the cluster + services.

**The trade-off, spelled out (this is the interview answer):**

| Option | Fit for inventory/booking | Why / why not |
|---|---|---|
| **EC2 (self-managed)** | ✗ | You patch the OS, right-size the box, handle bin-packing. Real control, real ops burden. Overkill for two stateless web services. |
| **Lambda** | ✗ | Spring Boot cold start is seconds; these are steady-load, long-lived request/response services with a warm connection pool to RDS. Lambda shines for spiky, short, stateless work (hold-expiry cleanup — that's Phase 6/8, not this). |
| **ECS Fargate** | ✓ | Stateless HTTP services, steady load, want zero server management + rolling deploys + ALB health integration. This is Fargate's exact sweet spot. |

- **FAILURE:** task crashes → ALB health check fails → ECS deregisters +
  launches a replacement. **This is the Day-5 experiment** (kill a task, watch
  the auto-replace + zero-downtime because the other AZ's task keeps serving).
- **SCALE:** bump desired count (manual in Week 4; target-tracking autoscaling
  is Phase 4). Fargate has no host to fill, so scaling = "more tasks."
- **SECURITY:** task role (2.2) + private subnet + SG from ALB only. No SSH,
  no host.
- **COST:** per vCPU-second + GB-second while running. Two small tasks (e.g.
  0.25 vCPU / 0.5 GB) × 2 services is cheap; the cost lever is desired count ×
  task size. Note: Fargate costs more per-unit than EC2 at high steady scale —
  the crossover is a real interview point (you pay for no-ops).

### 2.5 ALB (Application Load Balancer)

- **WHY:** one stable public entry point + health-based routing + TLS
  termination, instead of exposing each task.
- **WHAT:** L7 load balancer — listeners (:80, later :443), rules that route
  by path/host to **target groups** (one per service), health checks that
  gate traffic.
- **HOW:** listener rule `/api/inventory/*` → inventory TG, `/api/booking/*`
  → booking TG; health check hits `/actuator/health` (already exposed via
  spring-boot-actuator in every service). **[Claude]** authors; **[Rajat]**
  creates.
- **TRADE-OFF:** NLB (L4, faster, no path routing) vs ALB (L7, path/host
  rules, HTTP-aware health). ALB — we route by path and want HTTP health.
- **FAILURE:** health check misconfig (wrong path/port/threshold) = ALB marks
  healthy tasks unhealthy → 503s. First thing to verify after deploy. This
  ties to Bug-class "it's up but the LB thinks it's down."
- **SCALE:** ALB scales itself; it's the front door for autoscaled tasks
  later.
- **SECURITY:** ALB SG open to world on :80/:443 only; TLS cert via ACM
  (Phase 5 does real certs — Week 4 can start HTTP-only, note the gap). WAF is
  Phase 5.
- **COST:** hourly + LCU (connections/rules/bandwidth). One ALB shared across
  both services (via path rules) keeps it to a single charge.

### 2.6 RDS Postgres (Multi-AZ)

- **WHY:** managed, durable, HA database — no more Postgres-in-docker that
  dies on `compose down`. Multi-AZ = automatic failover.
- **WHAT:** managed Postgres; Multi-AZ keeps a synchronous standby in a second
  AZ and fails over on primary loss. Two databases on one instance for Week 4
  (`inventory`, `booking`) — mirrors the local `db-init/` split.
- **HOW:** DB subnet group over the private subnets; SG allows :5432 from the
  ECS SG only; master credential in Secrets Manager (2.7). **Flyway already
  owns the schema** (rule §3-10) — each service runs its `V1__*.sql` on first
  connect, `baseline-on-migrate` adopts a populated instance. **[Rajat]**
  creates the instance; **[Claude]** verifies the Flyway migration runs
  cleanly against it.
- **TRADE-OFF:** RDS vs Aurora (Aurora = better read-scaling + faster
  failover, more $$; Phase 3 introduces read replicas) vs DynamoDB (Phase 4,
  for the idempotency store specifically). Plain RDS Postgres for Week 4 — same
  engine as local, least surprise.
- **FAILURE:** primary dies → Multi-AZ failover (~60–120s, DNS flips to
  standby). The app's connection pool must reconnect — HikariCP does; note it.
  This is a Phase-9 chaos experiment target; Week 4 just enables Multi-AZ.
- **SCALE:** vertical (instance class) + read replicas later. Single writer.
- **SECURITY:** private subnet, no public access, SG from ECS only, encryption
  at rest (KMS — default key Week 4, CMK Phase 5), creds in Secrets Manager
  never in env-plaintext.
- **COST:** biggest steady line item. Multi-AZ ~doubles single-AZ. `db.t3.micro`
  / `t4g.micro` for Week 4; note that Multi-AZ is a deliberate cost for the HA
  lesson — could run single-AZ to save if budget matters, documented either way.

### 2.7 Secrets Manager

- **WHY:** DB credentials must not live in `.env`, task-def plaintext, or the
  image. Rule §3 (no hardcoded creds) enforced by infra, not discipline.
- **WHAT:** managed secret store; the task-def references a secret ARN and ECS
  injects it as an env var at container start (via the execution role).
- **HOW:** RDS master secret (can be auto-managed by RDS) + an app secret per
  service; task-def `secrets:` block maps ARN → `SPRING_DATASOURCE_PASSWORD`.
  **[Claude]** writes the mapping; **[Rajat]** creates the secrets.
- **TRADE-OFF:** SSM Parameter Store (cheaper, free tier, manual rotation) vs
  Secrets Manager (rotation built-in, priced per secret). Week 4: Secrets
  Manager for DB creds (rotation story matters for the interview), Parameter
  Store fine for non-secret config. Note the choice explicitly.
- **FAILURE:** task can't read secret (IAM) → won't start; visible in ECS
  events. Rotation mid-run without app reconnect = stale creds (Phase 5
  concern).
- **SCALE:** n/a.
- **SECURITY:** the whole point. Encrypted at rest (KMS); access gated by the
  execution role's exact secret ARN.
- **COST:** per-secret-month + per-10k API calls. A handful of secrets = cents.

---

## 3. The service-to-service hop — first real "network is not localhost"

In Week 3, `booking-service` calls `inventory-service` at
`http://localhost:8081` (or the compose service name). On AWS that address is
gone. Two options, decide before Day 3:

- **A — via the ALB** (booking → ALB internal path → inventory TG). Simple,
  reuses the LB, one code change (base URL → ALB DNS). Adds an LB hop of
  latency; the call leaves and re-enters the network.
- **B — ECS Service Connect / Cloud Map service discovery**
  (`inventory.ticketing.local`). Direct task-to-task, no LB hop, DNS-based.
  More setup, the "correct" microservice answer.

**Week-4 pick: A (ALB path).** Fewer moving parts for the first landing;
Service Connect is a clean Week-5/Phase-3 upgrade when async also lands. The
`InventoryClient` base URL is already config-driven (`inventory.base-url`), so
this is a config change, not a code change — Resilience4j timeout/retry/CB
already wrap it, so a slow ALB hop degrades gracefully. Document the latency
trade so the Phase-3 switch to Service Connect has a "why" attached.

---

## 4. Terraform layout — what [Claude] will scaffold (Day 2)

IaC so the whole environment is `terraform apply` / `destroy` reproducible.
Skeleton only in Week 4 (real `apply` is **[Rajat]**):

```
ticketing-platform/infra/terraform/
├── main.tf            # provider (aws, region), backend (S3 state — [Rajat] makes the bucket)
├── variables.tf       # region, cidr, db_instance_class, desired_count, image tags
├── outputs.tf         # alb_dns_name, rds_endpoint, ecr_repo_urls
├── vpc.tf             # VPC + 4 subnets + IGW + NAT + route tables
├── security.tf        # 3 SGs (alb, ecs, rds) referencing each other by id
├── iam.tf             # execution role + task role + scoped policies
├── ecr.tf             # 2 repos + lifecycle policy
├── rds.tf             # subnet group + instance (multi_az=true) + master secret
├── secrets.tf         # app secrets + ARNs wired to task-defs
├── ecs.tf             # cluster + 2 task-defs + 2 services
└── alb.tf             # ALB + listener + 2 target groups + rules + health checks
```

Rules carried in: state in S3 (**[Rajat]** creates the bucket per §3-2, so
Terraform itself isn't bootstrapping AWS creds silently); never edit a shipped
resource's identity out from under state; `terraform plan` is the review
artifact **[Claude]** reads before **[Rajat]** applies.

---

## 5. Deploy sequence (Day 3–4) — who does what

1. **[Rajat]** create S3 state bucket + ECR repos (or via first `apply`).
2. **[Rajat]** build + push images: `docker build --platform linux/amd64` →
   tag with git SHA → `docker push` to ECR. **[Claude]** provides exact cmds.
3. **[Rajat]** `terraform apply` the VPC/SG/IAM/RDS/Secrets/ALB/ECS.
   **[Claude]** reviews the `plan` first.
4. **[Claude]** verify: ALB DNS → `/api/inventory/actuator/health` returns
   `UP`; same for booking; RDS reachable only from tasks; Flyway `V1` ran
   (check `flyway_schema_history`).
5. **[Claude]** E2E: `POST /api/booking/bookings` end-to-end → booking
   CONFIRMED, inventory seat BOOKED — the Week-2 guarantee, now across AWS.

---

## 6. Day-5 failure experiment (planned)

**Primary:** ECS task crash → ALB health check fails → task auto-replaced,
zero downtime because the second AZ task keeps serving. Kill via
`aws ecs stop-task`, watch service events + ALB target health, confirm a new
task registers and the other never dropped a request.

**Secondary (if time):** tighten the RDS SG to *remove* the ECS-SG ingress →
watch the app fail to connect (connection timeout, not crash — degrade
visible in `/actuator/health` DB indicator) → restore → recover. Proves the
SG is the actual boundary, not decoration.

---

## 7. Open questions — decide before Day 2

1. **One RDS instance, two databases** (cheaper, Week-4 simple) **vs two
   instances** (stronger isolation, more $$). Lean: one instance, two DBs —
   matches local, defer split to when a service needs independent scaling.
2. **Multi-AZ RDS now** (the HA lesson, ~2× cost) **vs single-AZ** (cheaper,
   add Multi-AZ in a Phase-9 chaos drill). Lean: Multi-AZ — it's the Week-4
   headline "managed HA" point; note the cost.
3. **HTTP-only ALB for Week 4** (defer ACM/TLS to Phase 5) **vs TLS now**.
   Lean: HTTP-only now, flag the gap loudly — don't pretend it's prod-secure.
4. **Fargate x86 vs ARM64** — ARM is cheaper; must match the image build
   `--platform`. Lean: x86 for least surprise now, revisit for cost.
5. **NAT: one GW (cost) vs one-per-AZ (HA).** Lean: one, documented compromise.

---

## 8. Interview questions (Weekend — answer FIRST, then evaluate)

Anchored to this week's real decisions; jump to the section, then answer.

1. **Fargate vs EC2 vs Lambda** for `inventory-service` — pick and justify
   with the two properties that decide it (§2.4). When would Lambda actually
   win on *this* platform?
2. **Task execution role vs task role** — what does each do, and what breaks
   if you collapse them into one role (§2.2)?
3. Why does the RDS security group reference the **ECS security group id**
   instead of the private-subnet CIDR? What attack does the id-reference
   model stop that a CIDR rule doesn't (§2.1)?
4. `booking → inventory` was `localhost` in Week 3. Name the two AWS ways to
   restore that call, and the latency/complexity trade between them (§3).
5. A deployed task passes its own `/actuator/health` but the ALB shows it
   **unhealthy** and returns 503. List three concrete misconfigs that cause
   this (§2.5).
6. Where do the RDS credentials live, and trace the exact path by which the
   Java process ends up with the password **without it ever being in the
   image or the task-def plaintext** (§2.7).
7. Multi-AZ RDS fails over. What does the application experience during the
   ~60–120s, and what in the Spring/Hikari stack makes it recover without a
   restart (§2.6)?

---

## 9. Day 1 Definition of Done

- [x] `WEEK4_DESIGN.md` written — topology, 8-question pass per service,
      Fargate decision, service-hop decision, Terraform layout, deploy
      sequence, failure experiment, open questions, 7 interview Qs.
- [x] **Week 4 showcase HTML** `WEEK4_CLOUD.html` shipped (Corner Notes, 7
      concept cards + build log + 4 inline-SVG diagrams + glossary).
- [x] **Day 2 Terraform skeleton** `infra/terraform/` authored (NOT applied,
      NOT locally validated — no terraform binary here; brace-balance
      self-checked). Note: the design listed a separate `secrets.tf`; the
      skeleton folds the secrets into `rds.tf` — same resources, one file.
- [~] Open questions §7: proceeded with the documented default leans (per
      Rajat's "work autonomously" directive) rather than blocking; Rajat
      confirms/adjusts at the AWS session via `example.tfvars`.
- [ ] Rajat answers §8 interview questions (answer-first, then evaluate).
- [x] **No AWS resource created** — design + skeleton only; first real
      resource is Rajat's.

> **Day 3+ (apply) starts** when Rajat sits down for AWS: `terraform
> init/validate/plan` → review → apply → build/push images → create the two
> DBs → `verify.sh`. Progressive, one day at a time — same rhythm as Weeks 1–3.
