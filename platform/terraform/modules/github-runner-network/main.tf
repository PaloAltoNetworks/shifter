# ------------------------------------------------------------------------------
# Dedicated GitHub Actions Runner Network (issue #1433, ADR-004-R20)
# ------------------------------------------------------------------------------
# A minimal, self-contained non-default VPC for the self-hosted deploy runner.
#
# Why a dedicated VPC: a range's `private_dns_enabled` interface VPC endpoints
# override AWS service hostnames for the entire VPC and can black-hole the
# runner's AWS API calls (the ~107-minute CI wedge behind #1220). Placing the
# runner in its own VPC with NAT-only egress and NO private-DNS interface
# endpoints removes that failure mode entirely: nothing in this VPC can hijack
# the runner's service resolution.
#
# Traffic flow: runner subnet (private) -> NAT gateway -> IGW -> internet.
# The runner reaches GitHub, ECR, SSM, STS, and CloudWatch over public
# endpoints via NAT, so no interface endpoints (and no private DNS) are created.
# ------------------------------------------------------------------------------

data "aws_caller_identity" "current" {}

data "aws_region" "current" {}

data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  common_tags = merge(var.tags, {
    Module = "github-runner-network"
  })
  # IAM resource names go through the iam_name_prefix seam (check-tf-iam-role-naming
  # / shifter-* prefix convention), falling back to name_prefix.
  iam_name_prefix = coalesce(var.iam_name_prefix, var.name_prefix)
  # Single AZ keeps the runner network cheap (one NAT gateway). The runner
  # fleet is not HA infrastructure; a replaced AZ is a re-apply, not an outage.
  primary_az = data.aws_availability_zones.available.names[0]
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

# Adopt the AWS-created default security group and strip its permissive rules so
# it can never carry traffic (Checkov CKV2_AWS_12). The runner uses the named SG
# created by the runner root, never this one.
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
# NAT subnet (public tier) + NAT gateway
# ------------------------------------------------------------------------------

resource "aws_subnet" "nat" {
  vpc_id                  = aws_vpc.this.id
  cidr_block              = cidrsubnet(var.vpc_cidr, 2, 0)
  availability_zone       = local.primary_az
  map_public_ip_on_launch = false

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-nat-subnet"
    Tier = "public"
  })
}

# checkov:skip=CKV2_AWS_19:EIP is attached to the NAT gateway, not an EC2 instance. See docs/adr/exceptions.yaml (ADR-004-R11, github-runner-network).
resource "aws_eip" "nat" {
  domain = "vpc"

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-nat-eip"
  })

  depends_on = [aws_internet_gateway.this]
}

resource "aws_nat_gateway" "this" {
  allocation_id = aws_eip.nat.id
  subnet_id     = aws_subnet.nat.id

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-nat"
  })

  depends_on = [aws_internet_gateway.this]
}

resource "aws_route_table" "nat" {
  vpc_id = aws_vpc.this.id

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-nat-rt"
  })
}

resource "aws_route" "nat_to_igw" {
  route_table_id         = aws_route_table.nat.id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.this.id
}

resource "aws_route_table_association" "nat" {
  subnet_id      = aws_subnet.nat.id
  route_table_id = aws_route_table.nat.id
}

# ------------------------------------------------------------------------------
# Runner subnet (private tier) + egress via NAT
# ------------------------------------------------------------------------------

resource "aws_subnet" "runner" {
  vpc_id                  = aws_vpc.this.id
  cidr_block              = cidrsubnet(var.vpc_cidr, 2, 1)
  availability_zone       = local.primary_az
  map_public_ip_on_launch = false

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-runner-subnet"
    Tier = "private"
  })
}

resource "aws_route_table" "runner" {
  vpc_id = aws_vpc.this.id

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-runner-rt"
  })
}

resource "aws_route" "runner_to_nat" {
  route_table_id         = aws_route_table.runner.id
  destination_cidr_block = "0.0.0.0/0"
  nat_gateway_id         = aws_nat_gateway.this.id
}

resource "aws_route_table_association" "runner" {
  subnet_id      = aws_subnet.runner.id
  route_table_id = aws_route_table.runner.id
}

# ------------------------------------------------------------------------------
# VPC Flow Logs (CKV2_AWS_11) with a customer-managed KMS key (CKV_AWS_158)
# ------------------------------------------------------------------------------

resource "aws_kms_key" "flow_logs" {
  count = var.enable_flow_logs ? 1 : 0

  description             = "CMK for ${var.name_prefix} VPC flow-log CloudWatch group (CKV_AWS_158)"
  enable_key_rotation     = true
  deletion_window_in_days = 30

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "EnableRootAccountAdmin"
        Effect    = "Allow"
        Principal = { AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root" }
        Action    = "kms:*"
        Resource  = "*"
      },
      {
        Sid       = "AllowCloudWatchLogs"
        Effect    = "Allow"
        Principal = { Service = "logs.${data.aws_region.current.region}.amazonaws.com" }
        Action = [
          "kms:Encrypt*",
          "kms:Decrypt*",
          "kms:ReEncrypt*",
          "kms:GenerateDataKey*",
          "kms:DescribeKey",
        ]
        Resource = "*"
        Condition = {
          ArnLike = {
            "kms:EncryptionContext:aws:logs:arn" = "arn:aws:logs:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:*"
          }
        }
      },
    ]
  })

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-flow-logs-cmk"
  })
}

resource "aws_cloudwatch_log_group" "flow_logs" {
  count = var.enable_flow_logs ? 1 : 0

  name              = "/vpc/${var.name_prefix}-flow-logs"
  retention_in_days = var.flow_log_retention_days
  kms_key_id        = aws_kms_key.flow_logs[0].arn

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-flow-logs"
  })
}

resource "aws_iam_role" "flow_logs" {
  count = var.enable_flow_logs ? 1 : 0

  name = "${local.iam_name_prefix}-flow-logs-role"

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
        "logs:CreateLogStream",
        "logs:PutLogEvents",
        "logs:DescribeLogGroups",
        "logs:DescribeLogStreams",
      ]
      Resource = "${aws_cloudwatch_log_group.flow_logs[0].arn}:*"
    }]
  })
}

resource "aws_flow_log" "this" {
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
