# All the knobs. Defaults = the WEEK4_DESIGN §7 leans; override in a
# *.tfvars file (Rajat) when provisioning for real.

variable "region" {
  description = "AWS region to deploy into."
  type        = string
  default     = "ap-south-1" # Mumbai — closest to the user
}

variable "vpc_cidr" {
  description = "CIDR for the whole VPC. /16 leaves room to grow (lean §7)."
  type        = string
  default     = "10.20.0.0/16"
}

variable "public_subnet_cidrs" {
  description = "One public subnet per AZ (ALB + NAT live here)."
  type        = list(string)
  default     = ["10.20.0.0/24", "10.20.1.0/24"]
}

variable "private_subnet_cidrs" {
  description = "One private subnet per AZ (ECS tasks + RDS live here)."
  type        = list(string)
  default     = ["10.20.10.0/24", "10.20.11.0/24"]
}

variable "single_nat_gateway" {
  description = "Week-4 lean §7-5: one NAT GW for cost (not HA). Set false for one-per-AZ in prod."
  type        = bool
  default     = true
}

variable "rds_multi_az" {
  description = "Week-4 lean §7-2: Multi-AZ on for the managed-HA lesson (~2x cost)."
  type        = bool
  default     = true
}

variable "rds_instance_class" {
  description = "Smallest sensible class for Week 4."
  type        = string
  default     = "db.t4g.micro"
}

variable "rds_engine_version" {
  description = "Postgres major to match local + the Flyway migrations."
  type        = string
  default     = "16"
}

variable "rds_allocated_storage" {
  description = "GB of storage for the RDS instance."
  type        = number
  default     = 20
}

variable "fargate_cpu" {
  description = "Task CPU units (256 = 0.25 vCPU). Small for Week 4."
  type        = number
  default     = 256
}

variable "fargate_memory" {
  description = "Task memory (MiB). 512 pairs with 256 CPU on Fargate."
  type        = number
  default     = 512
}

variable "fargate_architecture" {
  description = "Week-4 lean §7-4: x86 for least surprise. ARM64 is cheaper (must match image build --platform)."
  type        = string
  default     = "X86_64"
  validation {
    condition     = contains(["X86_64", "ARM64"], var.fargate_architecture)
    error_message = "fargate_architecture must be X86_64 or ARM64."
  }
}

variable "desired_count" {
  description = "Tasks per service. 2 = one per AZ (no autoscaling in Week 4; that's Phase 4)."
  type        = number
  default     = 2
}

variable "image_tag" {
  description = "Immutable image tag pushed to ECR (git SHA, never 'latest')."
  type        = string
  default     = "REPLACE_WITH_GIT_SHA"
}

variable "enable_https" {
  description = "Week-4 lean §7-3: HTTP-only for now (false). Flip true + supply acm_certificate_arn in Phase 5."
  type        = bool
  default     = false
}

variable "acm_certificate_arn" {
  description = "ACM cert ARN for the HTTPS listener (Phase 5). Empty in Week 4."
  type        = string
  default     = ""
}
