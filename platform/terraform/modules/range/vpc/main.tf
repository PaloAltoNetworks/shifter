# Range VPC Module
#
# Stable infrastructure for per-user range subnets.
# Creates VPC, IGW, NAT Gateway, Network Firewall, and private route table.
# User subnets are ephemeral (created by provisioner Lambda).
#
# Traffic flow: User Subnet -> Network Firewall -> NAT Gateway -> IGW -> Internet
# Domain-based egress filtering via AWS Network Firewall allowlists.

locals {
  common_tags = merge(var.tags, {
    Module = "range-vpc"
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
# default rules (open intra-SG ingress, open egress). All range traffic flows
# through named security groups and the Network Firewall; the default SG must
# never be attached to any workload. Satisfies Checkov CKV2_AWS_12.

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
# Route Tables - See nat.tf and firewall.tf
# ------------------------------------------------------------------------------
# - aws_route_table.private (in firewall.tf) - User subnets route through firewall
# - aws_route_table.firewall (in firewall.tf) - Firewall routes to NAT
# - aws_route_table.nat (in nat.tf) - NAT routes to IGW

# ------------------------------------------------------------------------------
# VPC Flow Logs
# ------------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "flow_logs" {
  count = var.enable_flow_logs ? 1 : 0

  name              = "/vpc/${var.name_prefix}-flow-logs"
  retention_in_days = var.firewall_log_retention_days
  kms_key_id        = aws_kms_key.range_vpc.arn

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-flow-logs"
  })
}

resource "aws_iam_role" "flow_logs" {
  count = var.enable_flow_logs ? 1 : 0

  name = "${var.name_prefix}-flow-logs-role"

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
