# narration-enrichment/infra — SQS for the P4 async pipeline

**Boundary (standing rule 3-2):** [Claude] authored `main.tf`;
**[Rajat] runs everything below and owns the real resources.** This
file has NOT been applied and NOT been locally validated (no
`terraform` binary on the authoring machine) — `init/validate/plan`
is the gate before any `apply`, same honest flag as
`../../infra/terraform/README.md` on the ticketing track.

## What it creates

| Resource | Purpose |
|---|---|
| `aws_sqs_queue.ingest` | The work queue. 15-min visibility timeout (one worst-case job attempt + headroom), 20s long-polling, 4-day retention |
| `aws_sqs_queue.ingest_dlq` | Poison-message net: after `max_receive_count` (default 5) failed deliveries, SQS moves the message here. 14-day retention — forensic evidence |

**DLQ vs DEAD (P4_DESIGN.md §7):** the DLQ catches messages whose
consumer *crashes before marking anything* (poison). The `ingest_jobs`
DEAD state catches work that *keeps failing cleanly*. Two nets, two
failure classes — do not tune one expecting it to cover the other.

## Rajat's run

```bash
cd narration-enrichment/infra
terraform init
terraform validate
terraform plan          # read it — two queues, one redrive policy
terraform apply
```

Then copy the two outputs into the (gitignored) `.env`:

```bash
INGEST_QUEUE_URL=<ingest_queue_url output>
INGEST_DLQ_URL=<ingest_dlq_url output>      # Day 5 ops visibility
```

Restart the API and start the worker (`uv run python -m
narration_enrichment.worker`) — `job_queue.get_queue()` picks SQS up
from the env var; zero code changes. Empty `INGEST_QUEUE_URL` falls
back to the in-memory queue (dev default).

## Live verification (Rajat-driven, Claude pairs)

1. `POST /policies/ingest-async` a real doc → 202 + job_id.
2. Watch the worker log claim → embed → DONE; `GET /jobs/{id}` flips.
3. Failure experiment: stop the worker mid-PROCESSING (Ctrl-C after
   the claim log line), wait out the visibility timeout, restart —
   the redelivery must be DROPPED by the CAS (job stays PROCESSING
   until the Day-5 sweep re-arms it). That's the at-least-once story
   proven live, not assumed.
