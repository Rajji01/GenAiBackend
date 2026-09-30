# Two ECS roles, least-privilege — WEEK4_DESIGN §2.2.
#   execution role: used by the ECS agent to pull the image + read the DB
#                   secret at container START.
#   task role:      the app's OWN runtime identity (what the Java process can
#                   call). Empty for Week 4 — inventory/booking call no AWS
#                   APIs directly yet; it exists so Week-5 SQS perms attach
#                   here, not to the execution role.

data "aws_iam_policy_document" "ecs_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

# --- Execution role ---
resource "aws_iam_role" "task_execution" {
  name               = "ticketing-ecs-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

# AWS-managed base (ECR pull + CloudWatch Logs write).
resource "aws_iam_role_policy_attachment" "execution_base" {
  role       = aws_iam_role.task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# Scoped secret-read: ONLY this project's DB secret ARNs, never "*".
# The tasks read their per-service app secret; the master is included for
# completeness (rotation/bootstrap tooling).
data "aws_iam_policy_document" "read_db_secret" {
  statement {
    actions = ["secretsmanager:GetSecretValue"]
    resources = concat(
      [aws_secretsmanager_secret.db_master.arn],
      [for s in aws_secretsmanager_secret.db_app : s.arn]
    )
  }
}

resource "aws_iam_role_policy" "execution_secret" {
  name   = "read-db-secret"
  role   = aws_iam_role.task_execution.id
  policy = data.aws_iam_policy_document.read_db_secret.json
}

# --- Task role (runtime identity; intentionally near-empty in Week 4) ---
resource "aws_iam_role" "task" {
  name               = "ticketing-ecs-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
  # Week 5 attaches SQS send/receive here. Week 4: no inline policy = the app
  # can call nothing in AWS, which is exactly right for two DB-only services.
}
