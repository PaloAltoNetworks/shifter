# ------------------------------------------------------------------------------
# TS Summit - Per-Team Range
# ------------------------------------------------------------------------------
# Stamps out a complete team range: NGFW, subnets, security groups, Windows
# Server, Windows Desktop, workstation, and webserver.
# Each team gets its own state backend and tfvars.
# ------------------------------------------------------------------------------

terraform {
  required_version = ">= 1.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }
  }

  backend "s3" {}
}

provider "aws" {
  region      = var.aws_region
  max_retries = 10

  default_tags {
    tags = {
      Project   = "tssummit"
      ManagedBy = "terraform"
      Team      = var.team_name
    }
  }
}

# ------------------------------------------------------------------------------
# Locals
# ------------------------------------------------------------------------------

locals {
  prefix = var.team_name
}

# ------------------------------------------------------------------------------
# Data Sources
# ------------------------------------------------------------------------------

data "aws_vpc" "default" {
  default = true
}

# ------------------------------------------------------------------------------
# Webserver (server subnet)
# ------------------------------------------------------------------------------

resource "aws_security_group" "webserver" {
  name        = "${local.prefix}-webserver-sg"
  description = "SSH access for WebServer"
  vpc_id      = data.aws_vpc.default.id

  tags = {
    Name = "${local.prefix}-webserver-sg"
  }
}

resource "aws_vpc_security_group_ingress_rule" "ssh" {
  for_each = var.ssh_allowed_cidrs

  security_group_id = aws_security_group.webserver.id
  description       = each.key
  from_port         = 22
  to_port           = 22
  ip_protocol       = "tcp"
  cidr_ipv4         = each.value
}

resource "aws_vpc_security_group_ingress_rule" "webserver_from_endpoint" {
  security_group_id = aws_security_group.webserver.id
  description       = "All from endpoint subnet"
  ip_protocol       = "-1"
  cidr_ipv4         = aws_subnet.endpoint.cidr_block
}

resource "aws_vpc_security_group_ingress_rule" "webserver_from_server" {
  security_group_id = aws_security_group.webserver.id
  description       = "All from server subnet"
  ip_protocol       = "-1"
  cidr_ipv4         = aws_subnet.server.cidr_block
}

resource "aws_vpc_security_group_ingress_rule" "webserver_admin" {
  for_each          = var.admin_allowed_cidrs
  security_group_id = aws_security_group.webserver.id
  description       = "${each.key} admin"
  ip_protocol       = "-1"
  cidr_ipv4         = each.value
}

resource "aws_vpc_security_group_egress_rule" "webserver_all" {
  security_group_id = aws_security_group.webserver.id
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_instance" "webserver" {
  ami                    = var.webserver_ami_id
  instance_type          = var.webserver_instance_type
  key_name               = var.key_name
  subnet_id              = aws_subnet.server.id
  vpc_security_group_ids = [aws_security_group.webserver.id]
  iam_instance_profile   = aws_iam_instance_profile.ssm_instance.name

  tags = {
    Name = "${var.team_name}WebServerStaging"
  }
}

resource "aws_eip" "webserver" {
  domain = "vpc"

  tags = {
    Name = "${local.prefix}-webserver"
  }
}

resource "aws_eip_association" "webserver" {
  instance_id   = aws_instance.webserver.id
  allocation_id = aws_eip.webserver.id
}
