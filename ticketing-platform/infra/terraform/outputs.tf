# What Rajat needs after apply — the front door + registry URLs to push to.

output "alb_dns_name" {
  description = "Public entry point. Hit http://<this>/api/inventory/actuator/health after deploy."
  value       = aws_lb.main.dns_name
}

output "rds_endpoint" {
  description = "RDS address (private — reachable only from ECS tasks)."
  value       = aws_db_instance.main.address
}

output "ecr_repository_urls" {
  description = "docker tag/push targets, per service."
  value       = { for k, r in aws_ecr_repository.service : k => r.repository_url }
}

output "db_master_secret_arn" {
  description = "Secrets Manager ARN of the RDS master credential."
  value       = aws_secretsmanager_secret.db_master.arn
}
