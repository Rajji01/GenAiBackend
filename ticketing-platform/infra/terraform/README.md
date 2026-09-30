# Week 4 — AWS foundation (Terraform skeleton)

> **Design source:** `../../WEEK4_DESIGN.md`. Read that first for the *why*.
> This directory is the *how* (skeleton).

## Status — read before touching

- **This is a skeleton, authored by Claude, NOT applied.**
- **It has NOT been validated locally** — there is no `terraform` binary on the
  build machine, so `terraform validate` has not run. Treat every file as a
  reviewed draft, not proven HCL. **Rajat runs `init` → `validate` → `plan`
  and reads the plan before any `apply`.**
- **No AWS resource exists until Rajat applies** (standing rule §3-2: real AWS
  creation is Rajat's). Claude never runs `apply`.
- Default variable values encode the `WEEK4_DESIGN.md` §7 "leans"
  (one RDS instance + two DBs, Multi-AZ on, HTTP-only ALB, x86 Fargate, single
  NAT). Override in a `*.tfvars` when the real session happens.

## Files

| File | What it declares |
|---|---|
| `main.tf` | providers, region, AZ lookup, the `services` map, (commented) S3 backend |
| `variables.tf` | every knob + the §7 leans as defaults |
| `vpc.tf` | VPC, 2 public + 2 private subnets, IGW, NAT, route tables |
| `security.tf` | 3 SGs chained by id: world → ALB → ECS → RDS |
| `iam.tf` | task-execution role (pull + read-secret) + task role (near-empty) |
| `ecr.tf` | one immutable repo per service + lifecycle prune |
| `rds.tf` | Postgres (Multi-AZ) + master/app secrets in Secrets Manager |
| `alb.tf` | ALB + per-service target groups + path-based listener rules |
| `ecs.tf` | cluster + task-defs (secret injection, logs) + services |
| `outputs.tf` | ALB DNS, RDS endpoint, ECR URLs, master secret ARN |
| `example.tfvars` | the §7 leans as overridable values — copy to a gitignored `prod.tfvars` |
| `verify.sh` | [Claude] post-deploy check: health of both services through the ALB + a booking-path probe (`ALB=<dns> ./verify.sh`) |

## Apply flow — who does what

1. **[Rajat]** create the Terraform state bucket + lock table, then uncomment
   the `backend "s3"` block in `main.tf`.
2. **[Rajat]** `terraform init`
3. **[Claude]** review — **[Rajat]** run `terraform validate` and
   `terraform plan -var image_tag=<git-sha>`; Claude reads the plan.
4. **[Rajat]** build + push images (x86 to match `fargate_architecture`):
   ```
   aws ecr get-login-password --region ap-south-1 \
     | docker login --username AWS --password-stdin <acct>.dkr.ecr.ap-south-1.amazonaws.com
   docker build --platform linux/amd64 -t ticketing/inventory-service:<git-sha> inventory-service
   docker tag  ticketing/inventory-service:<git-sha> <ecr_url>:<git-sha>
   docker push <ecr_url>:<git-sha>
   # repeat for booking-service
   ```
5. **[Rajat]** `terraform apply -var image_tag=<git-sha>`
6. **[Rajat]** create the `inventory` + `booking` databases on the instance
   (one instance, two DBs — same as local `db-init/`), e.g. `psql -h <rds> -c
   'CREATE DATABASE inventory;'` and `booking`. (Flyway then builds each
   schema on first service start.)
7. **[Claude]** verify: run `ALB=$(terraform output -raw alb_dns_name) ./verify.sh`
   — checks both services' `/actuator/health` through the ALB and probes the
   booking path. Then confirm RDS is reachable only from tasks and
   `flyway_schema_history` is populated.

## Teardown

`terraform destroy` (Rajat). `skip_final_snapshot=true` and
`deletion_protection=false` are set so Week-4 infra is fully disposable —
flip both for anything that must not be lost.
