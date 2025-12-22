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

# checkov:skip=CKV2_AWS_12:Default SG restriction deferred - see #221
resource "aws_vpc" "this" {
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-vpc"
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
# Victim Security Group (shared by all victim EC2 instances)
# ------------------------------------------------------------------------------

# checkov:skip=CKV2_AWS_5:SG used by dynamically provisioned EC2 instances
# Note: All rules defined as standalone aws_security_group_rule resources below
# to avoid conflicts between inline rules and standalone rules.
resource "aws_security_group" "victim" {
  name        = "${var.name_prefix}-victim"
  description = "Security group for victim EC2 instances"
  vpc_id      = aws_vpc.this.id

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-victim-sg"
  })

  lifecycle {
    create_before_destroy = true
  }
}

# ------------------------------------------------------------------------------
# Kali Security Group (shared by all Kali attack instances)
# ------------------------------------------------------------------------------

# checkov:skip=CKV2_AWS_5:SG used by dynamically provisioned EC2 instances
# Note: All rules defined as standalone aws_security_group_rule resources below
# to avoid conflicts between inline rules and standalone rules.
resource "aws_security_group" "kali" {
  name        = "${var.name_prefix}-kali"
  description = "Security group for Kali attack EC2 instances"
  vpc_id      = aws_vpc.this.id

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-kali-sg"
  })

  lifecycle {
    create_before_destroy = true
  }
}

# ------------------------------------------------------------------------------
# Victim Security Group Rules
# ------------------------------------------------------------------------------

resource "aws_security_group_rule" "victim_ssh_from_range" {
  type              = "ingress"
  from_port         = 22
  to_port           = 22
  protocol          = "tcp"
  cidr_blocks       = [var.vpc_cidr]
  security_group_id = aws_security_group.victim.id
  description       = "SSH from Range VPC"
}

resource "aws_security_group_rule" "victim_ssh_from_portal" {
  type              = "ingress"
  from_port         = 22
  to_port           = 22
  protocol          = "tcp"
  cidr_blocks       = [var.portal_vpc_cidr]
  security_group_id = aws_security_group.victim.id
  description       = "SSH from Portal VPC (browser terminal)"
}

resource "aws_security_group_rule" "victim_from_kali" {
  type                     = "ingress"
  from_port                = 0
  to_port                  = 0
  protocol                 = "-1"
  source_security_group_id = aws_security_group.kali.id
  security_group_id        = aws_security_group.victim.id
  description              = "All traffic from Kali"
}

resource "aws_security_group_rule" "victim_to_kali" {
  type                     = "egress"
  from_port                = 0
  to_port                  = 0
  protocol                 = "-1"
  source_security_group_id = aws_security_group.kali.id
  security_group_id        = aws_security_group.victim.id
  description              = "All traffic to Kali (reverse shells)"
}

resource "aws_security_group_rule" "victim_https_to_vpc" {
  type              = "egress"
  from_port         = 443
  to_port           = 443
  protocol          = "tcp"
  cidr_blocks       = [var.vpc_cidr]
  security_group_id = aws_security_group.victim.id
  description       = "HTTPS to VPC (SSM endpoints)"
}

resource "aws_security_group_rule" "victim_https_to_internet" {
  type              = "egress"
  from_port         = 443
  to_port           = 443
  protocol          = "tcp"
  cidr_blocks       = ["0.0.0.0/0"]
  security_group_id = aws_security_group.victim.id
  description       = "HTTPS for XDR (filtered by ANFW)"
}

resource "aws_security_group_rule" "victim_dns_udp" {
  type              = "egress"
  from_port         = 53
  to_port           = 53
  protocol          = "udp"
  cidr_blocks       = ["0.0.0.0/0"]
  security_group_id = aws_security_group.victim.id
  description       = "DNS UDP"
}

resource "aws_security_group_rule" "victim_dns_tcp" {
  type              = "egress"
  from_port         = 53
  to_port           = 53
  protocol          = "tcp"
  cidr_blocks       = ["0.0.0.0/0"]
  security_group_id = aws_security_group.victim.id
  description       = "DNS TCP"
}

# ------------------------------------------------------------------------------
# Kali Security Group Rules
# ------------------------------------------------------------------------------

resource "aws_security_group_rule" "kali_ssh_from_range" {
  type              = "ingress"
  from_port         = 22
  to_port           = 22
  protocol          = "tcp"
  cidr_blocks       = [var.vpc_cidr]
  security_group_id = aws_security_group.kali.id
  description       = "SSH from Range VPC"
}

resource "aws_security_group_rule" "kali_ssh_from_portal" {
  type              = "ingress"
  from_port         = 22
  to_port           = 22
  protocol          = "tcp"
  cidr_blocks       = [var.portal_vpc_cidr]
  security_group_id = aws_security_group.kali.id
  description       = "SSH from Portal VPC (browser terminal)"
}

resource "aws_security_group_rule" "kali_from_victim" {
  type                     = "ingress"
  from_port                = 0
  to_port                  = 0
  protocol                 = "-1"
  source_security_group_id = aws_security_group.victim.id
  security_group_id        = aws_security_group.kali.id
  description              = "All traffic from victim (reverse shells)"
}

resource "aws_security_group_rule" "kali_to_vpc" {
  type              = "egress"
  from_port         = 0
  to_port           = 0
  protocol          = "-1"
  cidr_blocks       = [var.vpc_cidr]
  security_group_id = aws_security_group.kali.id
  description       = "All traffic to VPC (attack victim)"
}

resource "aws_security_group_rule" "kali_dns_udp" {
  type              = "egress"
  from_port         = 53
  to_port           = 53
  protocol          = "udp"
  cidr_blocks       = ["0.0.0.0/0"]
  security_group_id = aws_security_group.kali.id
  description       = "DNS UDP"
}

resource "aws_security_group_rule" "kali_dns_tcp" {
  type              = "egress"
  from_port         = 53
  to_port           = 53
  protocol          = "tcp"
  cidr_blocks       = ["0.0.0.0/0"]
  security_group_id = aws_security_group.kali.id
  description       = "DNS TCP"
}

# ------------------------------------------------------------------------------
# VPC Flow Logs
# ------------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "flow_logs" {
  count = var.enable_flow_logs ? 1 : 0

  name              = "/vpc/${var.name_prefix}-flow-logs"
  retention_in_days = var.firewall_log_retention_days

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
