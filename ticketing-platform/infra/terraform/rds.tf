# RDS Postgres (Multi-AZ) + the master credential in Secrets Manager —
# WEEK4_DESIGN §2.6 + §2.7. One instance, two databases (lean §7-1): the
# instance is created empty with an `app` bootstrap DB; the `inventory` and
# `booking` databases are created on first connect the same way local
# db-init/ does (a small init step, run by Rajat, or a Flyway callback).
#
# Schema WITHIN each DB is owned by Flyway (rule §3-10) — each service runs
# its own V1__*.sql on startup; baseline-on-migrate adopts the instance.

# --- Master credential: generated, stored, never printed to code/state-plain ---
resource "random_password" "db_master" {
  length  = 24
  special = false # keep it URL/connection-string safe
}

resource "aws_secretsmanager_secret" "db_master" {
  name        = "ticketing/rds/master"
  description = "RDS master credential for the ticketing Postgres instance"
}

resource "aws_secretsmanager_secret_version" "db_master" {
  secret_id = aws_secretsmanager_secret.db_master.id
  secret_string = jsonencode({
    username = "ticketing_admin"
    password = random_password.db_master.result
  })
}

# --- Subnet group over the private subnets ---
resource "aws_db_subnet_group" "main" {
  name       = "ticketing-db-subnet-group"
  subnet_ids = aws_subnet.private[*].id
  tags       = { Name = "ticketing-db-subnet-group" }
}

# --- The instance ---
resource "aws_db_instance" "main" {
  identifier     = "ticketing-postgres"
  engine         = "postgres"
  engine_version = var.rds_engine_version
  instance_class = var.rds_instance_class

  allocated_storage = var.rds_allocated_storage
  storage_type      = "gp3"
  storage_encrypted = true # KMS default key in Week 4; CMK in Phase 5

  db_name  = "app" # bootstrap DB; inventory + booking created on top
  username = "ticketing_admin"
  password = random_password.db_master.result

  multi_az               = var.rds_multi_az
  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.rds.id]
  publicly_accessible    = false

  backup_retention_period = 7
  skip_final_snapshot     = true # Week 4 is disposable; flip false for prod
  deletion_protection     = false

  tags = { Name = "ticketing-postgres" }
}

# Per-service app secret: the JDBC connection info each task reads at start.
# Password is the master for Week 4 (single-instance); Phase 5 gives each
# service its own DB user + rotation.
resource "aws_secretsmanager_secret" "db_app" {
  for_each    = local.services
  name        = "ticketing/rds/${each.key}"
  description = "DB connection secret for ${each.key}-service"
}

resource "aws_secretsmanager_secret_version" "db_app" {
  for_each  = local.services
  secret_id = aws_secretsmanager_secret.db_app[each.key].id
  secret_string = jsonencode({
    url      = "jdbc:postgresql://${aws_db_instance.main.address}:5432/${each.value.db_name}"
    username = "ticketing_admin"
    password = random_password.db_master.result
  })
}
