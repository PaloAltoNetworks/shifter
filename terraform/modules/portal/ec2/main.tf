# EC2 Module - Django portal instance
#
# Creates:
# - EC2 instance with Docker (Amazon Linux 2023)
# - Security group (app port from ALB only)
# - IAM role and instance profile (ECR pull, Secrets Manager read, SSM)

locals {
  common_tags = merge(var.tags, {
    Module = "ec2"
  })
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

resource "aws_iam_role_policy" "ecr_pull" {
  name = "ecr-pull"
  role = aws_iam_role.this.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "ecr:GetAuthorizationToken"
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage"
        ]
        Resource = var.ecr_repository_arn
      }
    ]
  })
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
        Resource = var.db_secret_arn
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
# Security Group
# ------------------------------------------------------------------------------

resource "aws_security_group" "this" {
  name        = "${var.name_prefix}-ec2-sg"
  description = "Security group for Django EC2 instance"
  vpc_id      = var.vpc_id

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-ec2-sg"
  })
}

resource "aws_security_group_rule" "app_from_alb" {
  type                     = "ingress"
  from_port                = var.app_port
  to_port                  = var.app_port
  protocol                 = "tcp"
  source_security_group_id = var.alb_security_group_id
  security_group_id        = aws_security_group.this.id
  description              = "App traffic from ALB"
}

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
  subnet_id              = var.subnet_id
  vpc_security_group_ids = [aws_security_group.this.id]
  iam_instance_profile   = aws_iam_instance_profile.this.name

  user_data = base64encode(templatefile("${path.module}/user_data.sh", {
    aws_region         = var.aws_region
    ecr_repository_url = var.ecr_repository_url
  }))

  root_block_device {
    volume_type           = "gp3"
    volume_size           = var.root_volume_size
    encrypted             = true
    delete_on_termination = true
  }

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-ec2"
  })

  lifecycle {
    ignore_changes = [ami]
  }
}
