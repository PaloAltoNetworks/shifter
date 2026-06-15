# ------------------------------------------------------------------------------
# GitHub Actions Self-Hosted Runner
# ------------------------------------------------------------------------------
# Provisions an EC2 on-demand instance to run GitHub Actions workflows.
# Access via SSM Session Manager (no SSH required).
# ------------------------------------------------------------------------------

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
  region = var.region

  default_tags {
    tags = {
      Project   = "shifter"
      Component = "github-runner"
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
    values = ["al2023-ami-2023.*-kernel-*-x86_64"]
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
  name        = "shifter-github-runner"
  description = "Security group for GitHub Actions runner"
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
    Name = "shifter-github-runner"
  }
}

# ------------------------------------------------------------------------------
# IAM Role for Runner
# ------------------------------------------------------------------------------

resource "aws_iam_role" "runner" {
  name = "shifter-github-runner"

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
  name = "shifter-github-runner"
  role = aws_iam_role.runner.name
}

# SSM for remote access (alternative to SSH). Keep this inline because the
# target AWS organization can deny iam:AttachRolePolicy via SCP.
resource "aws_iam_role_policy" "ssm" {
  # checkov:skip=CKV_AWS_288:SSM managed-instance agent permissions require wildcard resources. See ADR-004-R11 exception aws-dev-runner-inline-ssm.

  name = "ssm-managed-instance-core"
  role = aws_iam_role.runner.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "ssm:DescribeAssociation",
          "ssm:GetDeployablePatchSnapshotForInstance",
          "ssm:GetDocument",
          "ssm:DescribeDocument",
          "ssm:GetManifest",
          "ssm:GetParameter",
          "ssm:GetParameters",
          "ssm:ListAssociations",
          "ssm:ListInstanceAssociations",
          "ssm:PutInventory",
          "ssm:PutComplianceItems",
          "ssm:PutConfigurePackageResult",
          "ssm:UpdateAssociationStatus",
          "ssm:UpdateInstanceAssociationStatus",
          "ssm:UpdateInstanceInformation",
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "ssmmessages:CreateControlChannel",
          "ssmmessages:CreateDataChannel",
          "ssmmessages:OpenControlChannel",
          "ssmmessages:OpenDataChannel",
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "ec2messages:AcknowledgeMessage",
          "ec2messages:DeleteMessage",
          "ec2messages:FailMessage",
          "ec2messages:GetEndpoint",
          "ec2messages:GetMessages",
          "ec2messages:SendReply",
        ]
        Resource = "*"
      },
    ]
  })
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
# EC2 On-Demand Instance
# ------------------------------------------------------------------------------

resource "aws_instance" "runner" {
  monitoring    = true
  ebs_optimized = true
  metadata_options {
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
    http_endpoint               = "enabled"
  }
  count         = var.runner_count
  ami           = data.aws_ami.al2023.id
  instance_type = var.instance_type

  vpc_security_group_ids = [aws_security_group.runner.id]
  subnet_id              = var.subnet_id
  iam_instance_profile   = aws_iam_instance_profile.runner.name

  root_block_device {
    volume_size = 50
    volume_type = "gp3"
  }

  user_data_base64 = base64encode(<<-EOF
    #!/bin/bash
    set -ex

    # Install build/runtime deps (docker, build chain) plus the .NET 6 runtime
    # libs that the Actions runner binary needs at startup.
    #
    # libicu / krb5-libs / zlib / lttng-ust / openssl-libs are what
    # `./bin/installdependencies.sh` would install on a recognised distro,
    # but that script identifies AL2023 as bare "fedora" and bails out, so
    # we install them ourselves at boot to avoid a manual second pass.
    dnf update -y
    dnf install -y docker git jq tar unzip python3.12 python3.12-pip python3.12-devel nodejs npm \
                   libicu krb5-libs zlib lttng-ust openssl-libs

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

    echo "Runner downloaded. Register with ./config.sh (see README)."
  EOF
  )

  tags = {
    Name = "shifter-github-runner-${count.index + 1}"
  }
}
