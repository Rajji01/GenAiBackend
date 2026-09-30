# One private image repo per service — WEEK4_DESIGN §2.3.
# scan-on-push = free basic CVE scan; lifecycle prunes old tags so storage
# stays small. Rajat builds with --platform matching var.fargate_architecture
# and pushes an immutable git-SHA tag (never 'latest').

resource "aws_ecr_repository" "service" {
  for_each             = local.services
  name                 = "ticketing/${each.key}-service"
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = { Name = "ticketing-${each.key}-ecr" }
}

# Keep only the last 10 images per repo.
resource "aws_ecr_lifecycle_policy" "service" {
  for_each   = aws_ecr_repository.service
  repository = each.value.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep last 10 images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = { type = "expire" }
    }]
  })
}
