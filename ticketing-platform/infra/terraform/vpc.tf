# VPC + 2 public + 2 private subnets + IGW + NAT + route tables.
# WEEK4_DESIGN §2.1. Public = ALB/NAT; private = ECS tasks + RDS (no public IP).

resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = { Name = "ticketing-vpc" }
}

resource "aws_internet_gateway" "igw" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = "ticketing-igw" }
}

resource "aws_subnet" "public" {
  count                   = length(var.public_subnet_cidrs)
  vpc_id                  = aws_vpc.main.id
  cidr_block              = var.public_subnet_cidrs[count.index]
  availability_zone       = local.azs[count.index]
  map_public_ip_on_launch = true
  tags                    = { Name = "ticketing-public-${local.azs[count.index]}", Tier = "public" }
}

resource "aws_subnet" "private" {
  count             = length(var.private_subnet_cidrs)
  vpc_id            = aws_vpc.main.id
  cidr_block        = var.private_subnet_cidrs[count.index]
  availability_zone = local.azs[count.index]
  tags              = { Name = "ticketing-private-${local.azs[count.index]}", Tier = "private" }
}

# --- Public routing: everything out via the IGW ---

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.igw.id
  }
  tags = { Name = "ticketing-public-rt" }
}

resource "aws_route_table_association" "public" {
  count          = length(aws_subnet.public)
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

# --- NAT: private-subnet egress (ECR pull, Secrets, etc.) ---
# Week-4 lean §7-5: one NAT GW for cost. Set single_nat_gateway=false for
# one-per-AZ (removes the single-AZ egress SPOF, doubles the NAT cost).

resource "aws_eip" "nat" {
  count  = var.single_nat_gateway ? 1 : length(aws_subnet.public)
  domain = "vpc"
  tags   = { Name = "ticketing-nat-eip-${count.index}" }
}

resource "aws_nat_gateway" "nat" {
  count         = var.single_nat_gateway ? 1 : length(aws_subnet.public)
  allocation_id = aws_eip.nat[count.index].id
  subnet_id     = aws_subnet.public[count.index].id
  tags          = { Name = "ticketing-nat-${count.index}" }
  depends_on    = [aws_internet_gateway.igw]
}

# One private route table per AZ so each can point at its own NAT when
# single_nat_gateway=false; when true, all point at nat[0].
resource "aws_route_table" "private" {
  count  = length(aws_subnet.private)
  vpc_id = aws_vpc.main.id
  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = var.single_nat_gateway ? aws_nat_gateway.nat[0].id : aws_nat_gateway.nat[count.index].id
  }
  tags = { Name = "ticketing-private-rt-${count.index}" }
}

resource "aws_route_table_association" "private" {
  count          = length(aws_subnet.private)
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private[count.index].id
}
