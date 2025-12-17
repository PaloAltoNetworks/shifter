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

# checkov:skip=CKV2_AWS_11:VPC flow logs deferred - see #220
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
resource "aws_security_group" "victim" {
  name        = "${var.name_prefix}-victim"
  description = "Security group for victim EC2 instances"
  vpc_id      = aws_vpc.this.id

  # SSH from within Range VPC (for MCP access)
  ingress {
    description = "SSH from Range VPC"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }

  # SSH from Portal VPC (for browser terminal)
  ingress {
    description = "SSH from Portal VPC (browser terminal)"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.portal_vpc_cidr]
  }

  # Allow all inbound from Kali (for attacks)
  ingress {
    description     = "All traffic from Kali"
    from_port       = 0
    to_port         = 0
    protocol        = "-1"
    security_groups = [aws_security_group.kali.id]
  }

  # HTTPS to VPC for SSM endpoints (required for Systems Manager agent)
  egress {
    description = "HTTPS to VPC (SSM endpoints)"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }

  # HTTPS for XDR agent telemetry (filtered by Network Firewall)
  egress {
    description = "HTTPS for XDR (filtered by ANFW)"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # DNS for domain resolution
  egress {
    description = "DNS UDP"
    from_port   = 53
    to_port     = 53
    protocol    = "udp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "DNS TCP"
    from_port   = 53
    to_port     = 53
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-victim-sg"
  })
}

# ------------------------------------------------------------------------------
# Kali Security Group (shared by all Kali attack instances)
# ------------------------------------------------------------------------------

# checkov:skip=CKV2_AWS_5:SG used by dynamically provisioned EC2 instances
resource "aws_security_group" "kali" {
  name        = "${var.name_prefix}-kali"
  description = "Security group for Kali attack EC2 instances"
  vpc_id      = aws_vpc.this.id

  # SSH from within Range VPC (for MCP/Chat UI access)
  ingress {
    description = "SSH from Range VPC"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }

  # SSH from Portal VPC (for browser terminal)
  ingress {
    description = "SSH from Portal VPC (browser terminal)"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.portal_vpc_cidr]
  }

  # All traffic within VPC (for attacking victim)
  egress {
    description = "All traffic to VPC (attack victim)"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = [var.vpc_cidr]
  }

  # DNS for internal resolution (filtered by Network Firewall for external)
  egress {
    description = "DNS UDP"
    from_port   = 53
    to_port     = 53
    protocol    = "udp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "DNS TCP"
    from_port   = 53
    to_port     = 53
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-kali-sg"
  })
}

# Allow victim to connect to Kali (reverse shells, callbacks)
resource "aws_security_group_rule" "kali_from_victim" {
  type                     = "ingress"
  from_port                = 0
  to_port                  = 0
  protocol                 = "-1"
  source_security_group_id = aws_security_group.victim.id
  security_group_id        = aws_security_group.kali.id
  description              = "All traffic from victim (reverse shells)"
}
