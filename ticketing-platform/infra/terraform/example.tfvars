# Example variable overrides — copy to a real `prod.tfvars` (gitignored) and
# tune. These values are the WEEK4_DESIGN §7 leans, spelled out so Rajat can
# flip any of them at the AWS session. Apply with:
#   terraform apply -var-file=prod.tfvars -var image_tag=$(git rev-parse --short HEAD)

region = "ap-south-1" # Mumbai

# --- §7-1: one RDS instance, two databases (cheaper; mirrors local) ---
# (No variable — the single-instance/two-DB shape is baked into rds.tf +
#  the services map. Split into two instances would be a code change.)

# --- §7-2: Multi-AZ RDS (managed-HA lesson, ~2x cost). ---
rds_multi_az       = true
rds_instance_class = "db.t4g.micro"

# --- §7-3: HTTP-only ALB for now; TLS/ACM is Phase 5. ---
enable_https = false
# acm_certificate_arn = "arn:aws:acm:ap-south-1:...:certificate/..."  # Phase 5

# --- §7-4: x86 Fargate (least surprise; must match `docker build --platform`). ---
fargate_architecture = "X86_64"
fargate_cpu          = 256
fargate_memory       = 512

# --- §7-5: single NAT gateway (cost; single-AZ-egress compromise). ---
single_nat_gateway = true

# Tasks per service (2 = one per AZ; no autoscaling in Week 4).
desired_count = 2

# image_tag is passed on the CLI (git SHA), not pinned here.
