# P4 Day 4 — SQS queue + DLQ for the async ingest pipeline.
#
# [Claude] authors this file; [Rajat] runs init/validate/plan/apply and
# owns every real AWS resource (standing rule 3-2). NOT applied from
# any Claude session, and NOT locally validated here (no terraform
# binary in the authoring environment — same honest flag as
# ticketing's infra/terraform/README.md).
#
# Design (P4_DESIGN.md §7): the DLQ catches POISON MESSAGES — messages
# whose consumer crashes before it can even mark the job FAILED. The
# job table's DEAD state catches work that keeps failing. Two
# different failures, two different nets; /ops/ingest surfaces both.

terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

variable "aws_region" {
  description = "Same region as the rest of the stack."
  type        = string
  default     = "ap-south-1"
}

variable "name_prefix" {
  description = "Prefix for both queue names."
  type        = string
  default     = "narration-ingest"
}

variable "max_receive_count" {
  description = <<-EOT
    Deliveries before SQS redrives a message to the DLQ. This guards
    POISON messages (consumer crashes pre-claim), not failing jobs —
    job retries are budgeted by INGEST_MAX_ATTEMPTS in the app. Keep
    it >= that value + 1 so the DLQ never races the app's own
    FAILED/DEAD bookkeeping.
  EOT
  type        = number
  default     = 5
}

resource "aws_sqs_queue" "ingest_dlq" {
  name = "${var.name_prefix}-dlq"
  # 14 days — the maximum. A poison message is forensic evidence; give
  # the operator the longest window SQS allows to look at it.
  message_retention_seconds = 1209600
}

resource "aws_sqs_queue" "ingest" {
  name = var.name_prefix

  # The worker claims a job then spends up to ~minutes embedding at
  # the 5/min free-tier cap. The visibility timeout must comfortably
  # exceed one job's worst-case attempt, or SQS redelivers mid-work
  # and the CAS claim starts dropping legitimate wake-ups as
  # duplicates. 15 min covers a 40-chunk doc (~8 min) with headroom.
  visibility_timeout_seconds = 900

  # Long-polling at the queue level — the worker's receive loop stays
  # a tight `ReceiveMessage` with no WaitTimeSeconds in code, and THIS
  # knob decides the poll economy (20s = max, fewest empty receives).
  receive_wait_time_seconds = 20

  message_retention_seconds = 345600 # 4 days

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.ingest_dlq.arn
    maxReceiveCount     = var.max_receive_count
  })
}

output "ingest_queue_url" {
  description = "Set this as INGEST_QUEUE_URL in .env (API + worker)."
  value       = aws_sqs_queue.ingest.url
}

output "ingest_dlq_url" {
  description = "Set this as INGEST_DLQ_URL in .env (ops visibility, Day 5)."
  value       = aws_sqs_queue.ingest_dlq.url
}
