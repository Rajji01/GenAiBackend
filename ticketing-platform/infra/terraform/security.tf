# Three security groups, chained by ID (not CIDR) — WEEK4_DESIGN §2.1.
# world → ALB → ECS tasks → RDS. Each layer only trusts the one in front of
# it. This is the "who, not where" model interview Q3 is about.

# ALB: open to the world on :80 (and :443 when HTTPS is enabled).
resource "aws_security_group" "alb" {
  name        = "ticketing-alb-sg"
  description = "ALB ingress from internet"
  vpc_id      = aws_vpc.main.id

  ingress {
    description = "HTTP from anywhere"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  dynamic "ingress" {
    for_each = var.enable_https ? [1] : []
    content {
      description = "HTTPS from anywhere"
      from_port   = 443
      to_port     = 443
      protocol    = "tcp"
      cidr_blocks = ["0.0.0.0/0"]
    }
  }

  egress {
    description = "All egress"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "ticketing-alb-sg" }
}

# ECS tasks: accept traffic ONLY from the ALB SG, on the app ports.
resource "aws_security_group" "ecs" {
  name        = "ticketing-ecs-sg"
  description = "ECS tasks ingress from ALB only"
  vpc_id      = aws_vpc.main.id

  egress {
    description = "All egress (ECR pull, RDS, Secrets via NAT)"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "ticketing-ecs-sg" }
}

# One ingress rule per service port, source = the ALB SG (by id).
resource "aws_security_group_rule" "ecs_from_alb" {
  for_each                 = local.services
  type                     = "ingress"
  security_group_id        = aws_security_group.ecs.id
  from_port                = each.value.port
  to_port                  = each.value.port
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.alb.id
  description              = "ALB -> ${each.key} task on ${each.value.port}"
}

# RDS: accept :5432 ONLY from the ECS SG (by id). Nothing else reaches the DB.
resource "aws_security_group" "rds" {
  name        = "ticketing-rds-sg"
  description = "RDS ingress from ECS tasks only"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "Postgres from ECS tasks"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "ticketing-rds-sg" }
}
