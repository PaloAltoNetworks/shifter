# Range VPC Module
#
# Stable infrastructure for per-user range subnets.
# Creates VPC, IGW, and public route table only.
# User subnets are ephemeral (created by user-subnet module).

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
# Internet Gateway
# ------------------------------------------------------------------------------

resource "aws_internet_gateway" "this" {
  vpc_id = aws_vpc.this.id

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-igw"
  })
}

# ------------------------------------------------------------------------------
# Public Route Table
# ------------------------------------------------------------------------------

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.this.id

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-public-rt"
  })
}

resource "aws_route" "public_internet" {
  route_table_id         = aws_route_table.public.id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.this.id
}

# ------------------------------------------------------------------------------
# Victim Security Group (shared by all victim EC2 instances)
# ------------------------------------------------------------------------------

resource "aws_security_group" "victim" {
  name        = "${var.name_prefix}-victim"
  description = "Security group for victim EC2 instances"
  vpc_id      = aws_vpc.this.id

  # SSH from within VPC (for MCP access)
  ingress {
    description = "SSH from VPC"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }

  # Allow all inbound from Kali (for attacks)
  ingress {
    description     = "All traffic from Kali"
    from_port       = 0
    to_port         = 0
    protocol        = "-1"
    security_groups = [aws_security_group.kali.id]
  }

  # Allow all outbound (for agent installation, updates)
  egress {
    description = "Allow all outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-victim-sg"
  })
}

# ------------------------------------------------------------------------------
# Kali Security Group (shared by all Kali attack instances)
# ------------------------------------------------------------------------------

resource "aws_security_group" "kali" {
  name        = "${var.name_prefix}-kali"
  description = "Security group for Kali attack EC2 instances"
  vpc_id      = aws_vpc.this.id

  # SSH from within VPC (for MCP/LibreChat access)
  ingress {
    description = "SSH from VPC"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }

  # Allow all outbound (for apt updates, attacking victim, etc.)
  egress {
    description = "Allow all outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
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
