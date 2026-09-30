# Week 4 AWS foundation — Terraform SKELETON (Day 2).
#
# STATUS: skeleton authored by Claude, NOT applied and NOT locally validated
# (no terraform binary on this machine). Rajat runs `terraform init &&
# terraform validate && terraform plan` and reviews the plan BEFORE any
# `apply`. No AWS resource exists until Rajat applies (standing rule §3-2).
#
# The default variable values encode the WEEK4_DESIGN §7 "leans" (one RDS
# instance / two DBs, Multi-AZ on, HTTP-only ALB, x86 Fargate, single NAT).
# Flip them in a *.tfvars when the AWS session happens.

terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # Remote state — Rajat creates the S3 bucket + DynamoDB lock table first,
  # then uncomment. Kept commented so `init` works locally against a scratch
  # backend while the design is still being reviewed.
  #
  # backend "s3" {
  #   bucket         = "ticketing-tfstate-<accountid>"
  #   key            = "week4/terraform.tfstate"
  #   region         = "ap-south-1"
  #   dynamodb_table = "ticketing-tf-locks"
  #   encrypt        = true
  # }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project   = "ticketing-platform"
      ManagedBy = "terraform"
      Phase     = "week4-aws-foundation"
    }
  }
}

# Two AZs is the Week-4 baseline (Multi-AZ RDS + one task per AZ).
data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  azs = slice(data.aws_availability_zones.available.names, 0, 2)

  # Services that land in Week 4. payment + notification follow once the
  # two-service shape is proven — add them here to extend.
  services = {
    inventory = {
      port         = 8081
      path_pattern = "/api/inventory/*"
      db_name      = "inventory"
    }
    booking = {
      port         = 8082
      path_pattern = "/api/booking/*"
      db_name      = "booking"
    }
  }
}
