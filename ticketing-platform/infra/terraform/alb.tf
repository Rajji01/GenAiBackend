# Public ALB, one target group per service, path-based routing —
# WEEK4_DESIGN §2.5. Health check hits /actuator/health (already exposed via
# spring-boot-actuator in every service). HTTP-only in Week 4 (lean §7-3);
# the HTTPS listener switches on when var.enable_https flips (Phase 5).

resource "aws_lb" "main" {
  name               = "ticketing-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = aws_subnet.public[*].id
  tags               = { Name = "ticketing-alb" }
}

resource "aws_lb_target_group" "service" {
  for_each    = local.services
  name        = "ticketing-${each.key}-tg"
  port        = each.value.port
  protocol    = "HTTP"
  vpc_id      = aws_vpc.main.id
  target_type = "ip" # Fargate awsvpc mode registers task ENIs by IP

  health_check {
    path                = "/actuator/health"
    port                = "traffic-port"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    timeout             = 5
    interval            = 15
    matcher             = "200"
  }

  tags = { Name = "ticketing-${each.key}-tg" }
}

# --- HTTP listener ---
# Default action returns 404 so an unmatched path is honest, not a silent
# route to some service. Per-service rules match the path patterns.
resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = "fixed-response"
    fixed_response {
      content_type = "text/plain"
      message_body = "no route"
      status_code  = "404"
    }
  }
}

resource "aws_lb_listener_rule" "service" {
  for_each     = local.services
  listener_arn = aws_lb_listener.http.arn

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.service[each.key].arn
  }

  condition {
    path_pattern {
      values = [each.value.path_pattern]
    }
  }
}

# --- HTTPS listener (Phase 5; only created when enabled) ---
resource "aws_lb_listener" "https" {
  count             = var.enable_https ? 1 : 0
  load_balancer_arn = aws_lb.main.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.acm_certificate_arn

  default_action {
    type = "fixed-response"
    fixed_response {
      content_type = "text/plain"
      message_body = "no route"
      status_code  = "404"
    }
  }
}
