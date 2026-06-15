# ------------------------------------------------------------------------------
# TS Summit
# ------------------------------------------------------------------------------
# Manages tssummit resources in the default VPC:
# - WebServer1: Created manually by fcasaloti@paloaltonetworks.com 2026-03-20
# - CTFd: shifter-ctfd instance with SSM access
# All migrated to Terraform on 2026-03-21.
# ------------------------------------------------------------------------------

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }
  }

  # Bucket/key supplied via -backend-config=dev.s3.tfbackend at init time.
  backend "s3" {
    bucket       = "OVERRIDDEN_VIA_BACKEND_CONFIG"
    key          = "OVERRIDDEN_VIA_BACKEND_CONFIG"
    region       = "us-east-2"
    encrypt      = true
    use_lockfile = true
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project   = "tssummit"
      ManagedBy = "terraform"
    }
  }
}

# ------------------------------------------------------------------------------
# Data Sources
# ------------------------------------------------------------------------------

data "aws_vpc" "default" {
  default = true
}

data "aws_subnet" "public" {
  id = var.subnet_id
}

# ------------------------------------------------------------------------------
# Security Group
# ------------------------------------------------------------------------------

resource "aws_security_group" "webserver" {
  name        = "tssummit-webserver-sg"
  description = "SSH access for tssummit WebServer1"
  vpc_id      = data.aws_vpc.default.id

  tags = {
    Name = "tssummit-webserver-sg"
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

# ------------------------------------------------------------------------------
# EC2 Instance
# ------------------------------------------------------------------------------

resource "aws_instance" "webserver1" {
  monitoring    = true
  ebs_optimized = true
  metadata_options {
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
    http_endpoint               = "enabled"
  }
  root_block_device {
    encrypted = true
  }
  ami                    = var.ami_id
  instance_type          = var.instance_type
  key_name               = var.key_name
  subnet_id              = var.subnet_id
  vpc_security_group_ids = [aws_security_group.webserver.id]

  associate_public_ip_address = true

  tags = {
    Name = "WebServer1"
  }
}

# ------------------------------------------------------------------------------
# Elastic IP
# ------------------------------------------------------------------------------

resource "aws_eip" "webserver1" {
  domain = "vpc"

  tags = {
    Name = "tssummit-webserver1-eip"
  }
}

resource "aws_eip_association" "webserver1" {
  instance_id   = aws_instance.webserver1.id
  allocation_id = aws_eip.webserver1.id
}

# ==============================================================================
# CTFd
# ==============================================================================

# ------------------------------------------------------------------------------
# IAM Role & Instance Profile
# ------------------------------------------------------------------------------

resource "aws_iam_role" "ctfd" {
  name = "shifter-ctfd"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Service = "ec2.amazonaws.com"
      }
      Action = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ctfd_ssm" {
  role       = aws_iam_role.ctfd.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "ctfd" {
  name = "shifter-ctfd"
  role = aws_iam_role.ctfd.name
}

# ------------------------------------------------------------------------------
# Security Group
# ------------------------------------------------------------------------------

resource "aws_security_group" "ctfd" {
  name        = "shifter-ctfd"
  description = "CTFd platform - HTTPS and SSM"
  vpc_id      = data.aws_vpc.default.id

  tags = {
    Name = "shifter-ctfd"
  }
}

resource "aws_vpc_security_group_ingress_rule" "ctfd_https" {
  security_group_id = aws_security_group.ctfd.id
  description       = "HTTPS"
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_vpc_security_group_ingress_rule" "ctfd_http" {
  security_group_id = aws_security_group.ctfd.id
  description       = "HTTP redirect to HTTPS"
  from_port         = 80
  to_port           = 80
  ip_protocol       = "tcp"
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_vpc_security_group_egress_rule" "ctfd_all" {
  security_group_id = aws_security_group.ctfd.id
  description       = "Ctfd egress (all protocols)"
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
}

# ------------------------------------------------------------------------------
# EC2 Instance
# ------------------------------------------------------------------------------

resource "aws_instance" "ctfd" {
  monitoring    = true
  ebs_optimized = true
  metadata_options {
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
    http_endpoint               = "enabled"
  }
  ami                    = var.ctfd_ami_id
  instance_type          = "t3.xlarge"
  subnet_id              = var.subnet_id
  vpc_security_group_ids = [aws_security_group.ctfd.id]
  iam_instance_profile   = aws_iam_instance_profile.ctfd.name
  user_data              = file("${path.module}/ctfd-userdata.sh")

  associate_public_ip_address = true

  root_block_device {
    volume_size           = 50
    volume_type           = "gp3"
    iops                  = 3000
    throughput            = 125
    delete_on_termination = true
  }

  tags = {
    Name = "shifter-ctfd"
  }

  lifecycle {
    ignore_changes  = [user_data]
    prevent_destroy = true
  }
}

# ------------------------------------------------------------------------------
# Elastic IP
# ------------------------------------------------------------------------------

resource "aws_eip" "ctfd" {
  domain = "vpc"

  tags = {
    Name = "shifter-ctfd"
  }
}

resource "aws_eip_association" "ctfd" {
  instance_id   = aws_instance.ctfd.id
  allocation_id = aws_eip.ctfd.id
}
