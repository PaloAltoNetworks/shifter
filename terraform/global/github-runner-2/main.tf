# ------------------------------------------------------------------------------
# GitHub Actions Self-Hosted Runner 2
# ------------------------------------------------------------------------------
# Provisions a second EC2 spot instance to run GitHub Actions workflows.
# Access via SSM Session Manager (no SSH required).
# ------------------------------------------------------------------------------

terraform {
  required_version = ">= 1.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  backend "s3" {}
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project   = "shifter"
      Component = "github-runner-2"
      ManagedBy = "terraform"
    }
  }
}

data "aws_caller_identity" "current" {}

# ------------------------------------------------------------------------------
# Latest Amazon Linux 2023 AMI
# ------------------------------------------------------------------------------

data "aws_ami" "al2023" {
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
# Security Group
# ------------------------------------------------------------------------------

resource "aws_security_group" "runner" {
  name        = "shifter-github-runner-2"
  description = "Security group for GitHub Actions runner 2"
  vpc_id      = var.vpc_id

  # No inbound rules needed - runner uses outbound HTTPS to GitHub
  # Access via SSM Session Manager (no SSH required)

  # All outbound (runner needs to reach GitHub, ECR, SSM endpoints, etc.)
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
    description = "All outbound"
  }

  tags = {
    Name = "shifter-github-runner-2"
  }
}

# ------------------------------------------------------------------------------
# IAM Role for Runner
# ------------------------------------------------------------------------------

resource "aws_iam_role" "runner" {
  name = "shifter-github-runner-2"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "ec2.amazonaws.com"
      }
    }]
  })
}

resource "aws_iam_instance_profile" "runner" {
  name = "shifter-github-runner-2"
  role = aws_iam_role.runner.name
}

# SSM for remote access (alternative to SSH)
resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.runner.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

# ECR access for Docker builds
resource "aws_iam_role_policy" "ecr" {
  name = "ecr-access"
  role = aws_iam_role.runner.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "ecr:GetAuthorizationToken",
        "ecr:BatchCheckLayerAvailability",
        "ecr:GetDownloadUrlForLayer",
        "ecr:BatchGetImage",
        "ecr:PutImage",
        "ecr:InitiateLayerUpload",
        "ecr:UploadLayerPart",
        "ecr:CompleteLayerUpload"
      ]
      Resource = "*"
    }]
  })
}

# ------------------------------------------------------------------------------
# EC2 Spot Instance
# ------------------------------------------------------------------------------

resource "aws_spot_instance_request" "runner" {
  ami                  = data.aws_ami.al2023.id
  instance_type        = var.instance_type
  spot_type            = "persistent"
  wait_for_fulfillment = true

  vpc_security_group_ids = [aws_security_group.runner.id]
  subnet_id              = var.subnet_id
  iam_instance_profile   = aws_iam_instance_profile.runner.name

  root_block_device {
    volume_size = 50
    volume_type = "gp3"
  }

  user_data = base64encode(<<-EOF
    #!/bin/bash
    set -ex

    # Install dependencies
    dnf update -y
    dnf install -y docker git jq tar unzip

    # Start Docker
    systemctl enable --now docker
    usermod -aG docker ec2-user

    # Create runner directory
    mkdir -p /home/ec2-user/actions-runner
    cd /home/ec2-user/actions-runner

    # Download latest runner
    RUNNER_VERSION=$(curl -s https://api.github.com/repos/actions/runner/releases/latest | jq -r .tag_name | sed 's/v//')
    curl -o actions-runner-linux-x64-$${RUNNER_VERSION}.tar.gz -L https://github.com/actions/runner/releases/download/v$${RUNNER_VERSION}/actions-runner-linux-x64-$${RUNNER_VERSION}.tar.gz
    tar xzf actions-runner-linux-x64-$${RUNNER_VERSION}.tar.gz
    chown -R ec2-user:ec2-user /home/ec2-user/actions-runner

    echo "Runner downloaded. SSH in and run ./config.sh to register."
  EOF
  )

  tags = {
    Name = "shifter-github-runner-2"
  }
}

# Tag the spot instance (spot requests don't propagate tags to instances)
resource "aws_ec2_tag" "runner_name" {
  resource_id = aws_spot_instance_request.runner.spot_instance_id
  key         = "Name"
  value       = "shifter-github-runner-2"
}
