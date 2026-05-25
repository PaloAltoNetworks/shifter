terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
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
      Project   = "shifter"
      Component = "ctfd-workshop"
      ManagedBy = "terraform"
    }
  }
}

data "aws_vpc" "default" {
  default = true
}

locals {
  instance_name = "shifter-ctfd-workshop"
}

resource "aws_iam_role" "ctfd" {
  name = local.instance_name

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

  tags = {
    Name = local.instance_name
  }
}

resource "aws_iam_role_policy_attachment" "ctfd_ssm" {
  role       = aws_iam_role.ctfd.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "ctfd" {
  name = local.instance_name
  role = aws_iam_role.ctfd.name
}

resource "aws_security_group" "ctfd" {
  name        = local.instance_name
  description = "Standalone CTFd platform for the workshop"
  vpc_id      = data.aws_vpc.default.id

  tags = {
    Name = local.instance_name
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
  description       = "HTTP redirect and ACME"
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

resource "aws_instance" "ctfd" {
  monitoring                  = true
  ebs_optimized               = true
  ami                         = var.ctfd_ami_id
  instance_type               = var.instance_type
  subnet_id                   = var.subnet_id
  vpc_security_group_ids      = [aws_security_group.ctfd.id]
  iam_instance_profile        = aws_iam_instance_profile.ctfd.name
  associate_public_ip_address = true
  user_data_replace_on_change = true

  user_data = templatefile("${path.module}/ctfd-userdata.sh.tftpl", {
    ctfd_git_ref           = var.ctfd_git_ref
    ctfd_repo_url          = var.ctfd_repo_url
    docker_buildx_version  = var.docker_buildx_version
    docker_compose_version = var.docker_compose_version
    domain                 = var.domain
  })

  metadata_options {
    http_endpoint = "enabled"
    http_tokens   = "required"
  }

  root_block_device {
    volume_size           = var.root_volume_size
    volume_type           = var.root_volume_type
    iops                  = var.root_volume_iops
    throughput            = var.root_volume_throughput
    delete_on_termination = true
  }

  tags = {
    Name = local.instance_name
  }
}

resource "aws_eip" "ctfd" {
  domain = "vpc"

  tags = {
    Name = local.instance_name
  }
}

resource "aws_eip_association" "ctfd" {
  instance_id   = aws_instance.ctfd.id
  allocation_id = aws_eip.ctfd.id
}
