# ECS Fargate cluster + one task-def and service per service —
# WEEK4_DESIGN §2.4. Tasks run in private subnets, no public IP, registered
# with their ALB target group. Secrets are injected from Secrets Manager by
# the execution role (never in the image or task-def plaintext). Logs go to
# CloudWatch.

resource "aws_ecs_cluster" "main" {
  name = "ticketing-cluster"
  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

resource "aws_cloudwatch_log_group" "service" {
  for_each          = local.services
  name              = "/ecs/ticketing/${each.key}"
  retention_in_days = 14
}

locals {
  # Booking must reach inventory; on AWS that's the ALB path, not localhost
  # (WEEK4_DESIGN §3). Spring relaxed-binding maps INVENTORY_BASE_URL ->
  # inventory.base-url, which InventoryClient already reads.
  extra_env = {
    inventory = []
    booking = [
      { name = "INVENTORY_BASE_URL", value = "http://${aws_lb.main.dns_name}/api/inventory" }
    ]
  }
}

resource "aws_ecs_task_definition" "service" {
  for_each                 = local.services
  family                   = "ticketing-${each.key}"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.fargate_cpu
  memory                   = var.fargate_memory
  execution_role_arn       = aws_iam_role.task_execution.arn
  task_role_arn            = aws_iam_role.task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = var.fargate_architecture
  }

  container_definitions = jsonencode([
    {
      name      = "${each.key}-service"
      image     = "${aws_ecr_repository.service[each.key].repository_url}:${var.image_tag}"
      essential = true

      portMappings = [
        { containerPort = each.value.port, protocol = "tcp" }
      ]

      environment = concat([
        { name = "SERVER_PORT", value = tostring(each.value.port) },
        { name = "SPRING_JPA_HIBERNATE_DDL_AUTO", value = "validate" }
      ], local.extra_env[each.key])

      # Pull individual JSON keys out of the per-service secret.
      secrets = [
        { name = "SPRING_DATASOURCE_URL", valueFrom = "${aws_secretsmanager_secret.db_app[each.key].arn}:url::" },
        { name = "SPRING_DATASOURCE_USERNAME", valueFrom = "${aws_secretsmanager_secret.db_app[each.key].arn}:username::" },
        { name = "SPRING_DATASOURCE_PASSWORD", valueFrom = "${aws_secretsmanager_secret.db_app[each.key].arn}:password::" }
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.service[each.key].name
          "awslogs-region"        = var.region
          "awslogs-stream-prefix" = each.key
        }
      }
    }
  ])
}

resource "aws_ecs_service" "service" {
  for_each        = local.services
  name            = "ticketing-${each.key}"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.service[each.key].arn
  desired_count   = var.desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.ecs.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.service[each.key].arn
    container_name   = "${each.key}-service"
    container_port   = each.value.port
  }

  # Don't fight the ALB during a rolling deploy; let health checks settle.
  health_check_grace_period_seconds = 60

  depends_on = [aws_lb_listener.http]
}
