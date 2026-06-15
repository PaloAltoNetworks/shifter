locals {
  common_tags = merge(var.tags, {
    Module = "ctfd"
  })

  instance_name = "${var.name_prefix}-ctfd"
}

resource "aws_key_pair" "this" {
  count = var.ssh_public_key != "" ? 1 : 0

  key_name   = "${local.instance_name}-ssh"
  public_key = var.ssh_public_key

  tags = merge(local.common_tags, {
    Name = "${local.instance_name}-ssh"
  })
}

resource "aws_iam_role" "this" {
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

  tags = merge(local.common_tags, {
    Name = local.instance_name
  })
}

resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.this.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "this" {
  name = local.instance_name
  role = aws_iam_role.this.name
}

resource "aws_security_group" "this" {
  name        = local.instance_name
  description = "Security group for standalone CTFd platform"
  vpc_id      = var.vpc_id

  tags = merge(local.common_tags, {
    Name = local.instance_name
  })
}

resource "aws_vpc_security_group_ingress_rule" "https" {
  security_group_id = aws_security_group.this.id
  description       = "HTTPS"
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_vpc_security_group_ingress_rule" "http" {
  security_group_id = aws_security_group.this.id
  description       = "HTTP redirect and ACME"
  from_port         = 80
  to_port           = 80
  ip_protocol       = "tcp"
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_vpc_security_group_ingress_rule" "ssh" {
  for_each = var.ssh_allowed_cidrs

  security_group_id = aws_security_group.this.id
  description       = each.key
  from_port         = 22
  to_port           = 22
  ip_protocol       = "tcp"
  cidr_ipv4         = each.value
}

resource "aws_vpc_security_group_egress_rule" "all" {
  security_group_id = aws_security_group.this.id
  description       = "all egress"
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_instance" "this" {
  monitoring                  = true
  ebs_optimized               = true
  ami                         = var.ami_id
  instance_type               = var.instance_type
  key_name                    = var.ssh_public_key != "" ? aws_key_pair.this[0].key_name : null
  subnet_id                   = var.subnet_id
  vpc_security_group_ids      = [aws_security_group.this.id]
  iam_instance_profile        = aws_iam_instance_profile.this.name
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

  tags = merge(local.common_tags, {
    Name = local.instance_name
  })
}

resource "aws_eip" "this" {
  domain = "vpc"

  tags = merge(local.common_tags, {
    Name = local.instance_name
  })
}

resource "aws_eip_association" "this" {
  instance_id   = aws_instance.this.id
  allocation_id = aws_eip.this.id
}
