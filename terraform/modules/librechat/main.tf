# LibreChat Module - Shared LibreChat instance
#
# Creates:
# - Dedicated subnet in Portal VPC
# - EC2 instance with Docker Compose (LibreChat + MongoDB)
# - Security group (egress only, SSM access via instance profile)
# - IAM role and instance profile (Secrets Manager read, SSM)
# - Secrets Manager secret for LibreChat configuration

data "aws_caller_identity" "current" {}

locals {
  common_tags = merge(var.tags, {
    Module = "librechat"
  })
}

# ------------------------------------------------------------------------------
# Subnet
# ------------------------------------------------------------------------------

resource "aws_subnet" "this" {
  vpc_id            = var.vpc_id
  cidr_block        = var.subnet_cidr
  availability_zone = var.availability_zone

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-subnet"
    Tier = "private"
  })
}

resource "aws_route_table_association" "this" {
  subnet_id      = aws_subnet.this.id
  route_table_id = var.private_route_table_id
}

# ------------------------------------------------------------------------------
# Security Group
# ------------------------------------------------------------------------------

resource "aws_security_group" "this" {
  name        = "${var.name_prefix}-sg"
  description = "Security group for LibreChat EC2 instance"
  vpc_id      = var.vpc_id

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-sg"
  })
}

# No ingress rules - SSM access only (via instance profile)

resource "aws_security_group_rule" "egress_all" {
  type              = "egress"
  from_port         = 0
  to_port           = 0
  protocol          = "-1"
  cidr_blocks       = ["0.0.0.0/0"]
  security_group_id = aws_security_group.this.id
  description       = "Allow all outbound"
}

# ------------------------------------------------------------------------------
# IAM Role for EC2
# ------------------------------------------------------------------------------

resource "aws_iam_role" "this" {
  name = "${var.name_prefix}-ec2-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ec2.amazonaws.com"
        }
      }
    ]
  })

  tags = local.common_tags
}

resource "aws_iam_role_policy" "secrets_read" {
  name = "secrets-read"
  role = aws_iam_role.this.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue"
        ]
        Resource = aws_secretsmanager_secret.librechat.arn
      }
    ]
  })
}

resource "aws_iam_role_policy" "cloudwatch_logs" {
  name = "cloudwatch-logs"
  role = aws_iam_role.this.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents",
          "logs:DescribeLogStreams"
        ]
        Resource = "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/ec2/${var.name_prefix}*"
      }
    ]
  })
}

resource "aws_iam_role_policy" "bedrock" {
  name = "bedrock-invoke"
  role = aws_iam_role.this.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel",
          "bedrock:InvokeModelWithResponseStream"
        ]
        Resource = [
          "arn:aws:bedrock:${var.aws_region}::foundation-model/*",
          # Account-specific inference profiles
          "arn:aws:bedrock:${var.aws_region}:${data.aws_caller_identity.current.account_id}:inference-profile/*",
          # Cross-region inference profiles (us.anthropic.*, eu.anthropic.*, etc.)
          "arn:aws:bedrock:${var.aws_region}::inference-profile/*"
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.this.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "this" {
  name = "${var.name_prefix}-ec2-profile"
  role = aws_iam_role.this.name

  tags = local.common_tags
}

# ------------------------------------------------------------------------------
# Secrets Manager
# ------------------------------------------------------------------------------

resource "random_password" "jwt_secret" {
  length  = 64
  special = false
}

resource "random_password" "jwt_refresh_secret" {
  length  = 64
  special = false
}

resource "random_password" "creds_key" {
  length  = 64
  special = false
}

resource "random_id" "creds_iv" {
  byte_length = 16
}

resource "aws_secretsmanager_secret" "librechat" {
  name                    = "shifter-${var.name_prefix}-config"
  description             = "LibreChat configuration secrets"
  recovery_window_in_days = 0

  tags = merge(local.common_tags, {
    Name = "shifter-${var.name_prefix}-config"
  })
}

resource "aws_secretsmanager_secret_version" "librechat" {
  secret_id = aws_secretsmanager_secret.librechat.id
  secret_string = jsonencode({
    jwt_secret         = random_password.jwt_secret.result
    jwt_refresh_secret = random_password.jwt_refresh_secret.result
    creds_key          = random_password.creds_key.result
    creds_iv           = random_id.creds_iv.hex
    allow_registration = var.allow_registration
    app_title          = var.app_title
  })
}

# ------------------------------------------------------------------------------
# AMI Lookup
# ------------------------------------------------------------------------------

data "aws_ami" "amazon_linux_2023" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-*-x86_64"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

# ------------------------------------------------------------------------------
# EC2 Instance
# ------------------------------------------------------------------------------

resource "aws_instance" "this" {
  ami                    = data.aws_ami.amazon_linux_2023.id
  instance_type          = var.instance_type
  subnet_id              = aws_subnet.this.id
  vpc_security_group_ids = [aws_security_group.this.id]
  iam_instance_profile   = aws_iam_instance_profile.this.name

  user_data = base64encode(templatefile("${path.module}/user_data.sh", {
    data_volume_device = "/dev/xvdf"
  }))
  user_data_replace_on_change = true

  root_block_device {
    volume_type           = "gp3"
    volume_size           = var.root_volume_size
    encrypted             = true
    delete_on_termination = true
  }

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required" # Enforce IMDSv2
    http_put_response_hop_limit = 2          # Allow containers to access IMDS
    instance_metadata_tags      = "enabled"
  }

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-ec2"
  })

  lifecycle {
    ignore_changes = [ami]
  }

  depends_on = [aws_secretsmanager_secret_version.librechat]
}

# ------------------------------------------------------------------------------
# EBS Volume for MongoDB Data
# ------------------------------------------------------------------------------

resource "aws_ebs_volume" "data" {
  availability_zone = var.availability_zone
  size              = var.data_volume_size
  type              = "gp3"
  encrypted         = true

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-data"
  })

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_volume_attachment" "data" {
  device_name = "/dev/xvdf"
  volume_id   = aws_ebs_volume.data.id
  instance_id = aws_instance.this.id
}

