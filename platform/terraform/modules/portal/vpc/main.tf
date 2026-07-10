# VPC Module - Reusable network infrastructure
#
# Creates:
# - VPC with DNS support
# - Public subnets (for ALB, NAT Gateway)
# - Private subnets (for RDS, ECS tasks)
# - Internet Gateway
# - NAT Gateway (single, cost-optimized)
# - Route tables

data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  azs = slice(data.aws_availability_zones.available.names, 0, var.az_count)

  iam_name_prefix = coalesce(var.iam_name_prefix, var.name_prefix)

  common_tags = merge(var.tags, {
    Module = "vpc"
  })
}

# ------------------------------------------------------------------------------
# VPC
# ------------------------------------------------------------------------------

resource "aws_vpc" "this" {
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-vpc"
  })
}

# ------------------------------------------------------------------------------
# Default Security Group — deny all
# ------------------------------------------------------------------------------
# Adopts the AWS-created default security group and removes the permissive
# default rules (open intra-SG ingress, open egress). All real traffic flows
# through named security groups defined in this module and its consumers; the
# default SG must never be attached to any workload. Satisfies Checkov
# CKV2_AWS_12.

resource "aws_default_security_group" "this" {
  vpc_id = aws_vpc.this.id

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-default-sg-deny-all"
  })
}

# ------------------------------------------------------------------------------
# Internet Gateway
# ------------------------------------------------------------------------------

resource "aws_internet_gateway" "this" {
  vpc_id = aws_vpc.this.id

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-igw"
  })
}

# ------------------------------------------------------------------------------
# Public Subnets (for ALB, NAT Gateway)
# ------------------------------------------------------------------------------

resource "aws_subnet" "public" {
  count = var.az_count

  vpc_id                  = aws_vpc.this.id
  cidr_block              = cidrsubnet(var.vpc_cidr, 4, count.index)
  availability_zone       = local.azs[count.index]
  map_public_ip_on_launch = true

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-public-${local.azs[count.index]}"
    Tier = "public"
  })
}

resource "aws_route_table" "public" {
  count = var.az_count

  vpc_id = aws_vpc.this.id

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-public-rt-${local.azs[count.index]}"
  })
}

resource "aws_route" "public_internet" {
  count = var.az_count

  route_table_id         = aws_route_table.public[count.index].id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.this.id
}

resource "aws_route_table_association" "public" {
  count = var.az_count

  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public[count.index].id
}

# ------------------------------------------------------------------------------
# NAT Gateway (single for cost optimization, can be per-AZ for HA)
# ------------------------------------------------------------------------------

# checkov:skip=CKV2_AWS_19:EIP attached to NAT Gateway, not EC2 - see #222
resource "aws_eip" "nat" {
  count  = var.enable_nat_gateway ? 1 : 0
  domain = "vpc"

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-nat-eip"
  })

  depends_on = [aws_internet_gateway.this]
}

resource "aws_nat_gateway" "this" {
  count = var.enable_nat_gateway ? 1 : 0

  allocation_id = aws_eip.nat[0].id
  subnet_id     = aws_subnet.public[0].id

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-nat"
  })

  depends_on = [aws_internet_gateway.this]
}

# ------------------------------------------------------------------------------
# Private Subnets (for RDS, ECS tasks)
# ------------------------------------------------------------------------------

resource "aws_subnet" "private" {
  count = var.az_count

  vpc_id            = aws_vpc.this.id
  cidr_block        = cidrsubnet(var.vpc_cidr, 4, count.index + var.az_count)
  availability_zone = local.azs[count.index]

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-private-${local.azs[count.index]}"
    Tier = "private"
  })
}

resource "aws_route_table" "private" {
  count = var.az_count

  vpc_id = aws_vpc.this.id

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-private-rt-${local.azs[count.index]}"
  })
}

resource "aws_route" "private_nat" {
  # When portal inspection is enabled, each private route table's default
  # route is owned by inspection.tf (private 0/0 -> same-AZ firewall
  # endpoint -> NAT) so private egress traverses the same firewall
  # endpoint as the NAT return path. Keeping a direct private->NAT
  # default here would make the inspection path asymmetric: NAT return
  # packets would enter the firewall via the public route table while
  # the initiating leg bypassed it, breaking stateful inspection for
  # unrelated private egress flows.
  count = var.enable_nat_gateway && !var.enable_portal_inspection ? var.az_count : 0

  route_table_id         = aws_route_table.private[count.index].id
  destination_cidr_block = "0.0.0.0/0"
  nat_gateway_id         = aws_nat_gateway.this[0].id
}

resource "aws_route_table_association" "private" {
  count = var.az_count

  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private[count.index].id
}

# ------------------------------------------------------------------------------
# Public-workload subnets (for CTFd and future standalone public EC2)
# ------------------------------------------------------------------------------
# A public tier kept SEPARATE from the ALB ingress (`public`) tier so the
# portal target-service security groups (Django:8000, Guacamole client:8080)
# can admit an ALB-only source CIDR without also admitting these workloads
# (#911 NET-2 / #933). Standalone internet-facing instances (CTFd has its own
# EIP, public IP, and ACME/HTTPS) live here; they reach the internet directly
# via the IGW. They are NOT routed through the portal inspection boundary —
# that boundary inspects the ALB<->private service path, and segmentation from
# these workloads is enforced by the target-service SGs, not by routing.
resource "aws_subnet" "public_workload" {
  count = var.az_count

  vpc_id                  = aws_vpc.this.id
  cidr_block              = cidrsubnet(var.vpc_cidr, 4, count.index + 2 * var.az_count)
  availability_zone       = local.azs[count.index]
  map_public_ip_on_launch = true

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-public-workload-${local.azs[count.index]}"
    Tier = "public-workload"
  })
}

resource "aws_route_table" "public_workload" {
  count = var.az_count

  vpc_id = aws_vpc.this.id

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-public-workload-rt-${local.azs[count.index]}"
  })
}

resource "aws_route" "public_workload_internet" {
  count = var.az_count

  route_table_id         = aws_route_table.public_workload[count.index].id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.this.id
}

resource "aws_route_table_association" "public_workload" {
  count = var.az_count

  subnet_id      = aws_subnet.public_workload[count.index].id
  route_table_id = aws_route_table.public_workload[count.index].id
}

# ------------------------------------------------------------------------------
# VPC Flow Logs
# ------------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "flow_logs" {
  count = var.enable_flow_logs ? 1 : 0

  name              = "/vpc/${var.name_prefix}-flow-logs"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.cloudwatch_logs.arn

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-flow-logs"
  })
}

resource "aws_iam_role" "flow_logs" {
  count = var.enable_flow_logs ? 1 : 0

  name = "${local.iam_name_prefix}-flow-logs-role"

  permissions_boundary = var.permissions_boundary_arn

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "vpc-flow-logs.amazonaws.com"
      }
    }]
  })

  tags = local.common_tags
}

resource "aws_iam_role_policy" "flow_logs" {
  count = var.enable_flow_logs ? 1 : 0

  name = "${var.name_prefix}-flow-logs-policy"
  role = aws_iam_role.flow_logs[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents",
        "logs:DescribeLogGroups",
        "logs:DescribeLogStreams"
      ]
      Resource = "*"
    }]
  })
}

resource "aws_flow_log" "main" {
  count = var.enable_flow_logs ? 1 : 0

  vpc_id               = aws_vpc.this.id
  traffic_type         = "ALL"
  log_destination_type = "cloud-watch-logs"
  log_destination      = aws_cloudwatch_log_group.flow_logs[0].arn
  iam_role_arn         = aws_iam_role.flow_logs[0].arn

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-flow-log"
  })
}
