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
# Network-isolation guard inputs (ADR-004-R20, issue #1222)
# ------------------------------------------------------------------------------
# The runner must never live in the account default VPC: a range's
# private_dns_enabled interface VPC endpoints override service hostnames for the
# entire VPC and black-hole the runner's AWS API calls (the ~107-minute CI
# wedge). Resolve the default VPC at plan time (list form, so an account with no
# default VPC - the desired end state - yields an empty list instead of an
# error) and the runner subnet, so the aws_security_group.runner preconditions
# below can fail closed on default-VPC placement instead of relying on a comment.
data "aws_vpcs" "default" {
  filter {
    name   = "is-default"
    values = ["true"]
  }
}

# When allow_default_vpc opts in and no explicit subnet is supplied, resolve a
# subnet of the account default VPC so no live subnet ID has to be committed
# (ADR-004-R14).
data "aws_subnets" "default" {
  count = var.allow_default_vpc && var.subnet_id == "" ? 1 : 0
  filter {
    name   = "vpc-id"
    values = [one(data.aws_vpcs.default.ids)]
  }
}

locals {
  # Resolve the runner network. Explicit vpc_id/subnet_id always win. Otherwise,
  # when allow_default_vpc is set, fall back to the account default VPC and its
  # first subnet. When neither is provided the values stay empty and the SG
  # preconditions / resource creation fail closed.
  runner_vpc_id    = var.vpc_id != "" ? var.vpc_id : (var.allow_default_vpc ? one(data.aws_vpcs.default.ids) : "")
  runner_subnet_id = var.subnet_id != "" ? var.subnet_id : (var.allow_default_vpc ? data.aws_subnets.default[0].ids[0] : "")
}

data "aws_subnet" "runner" {
  id = local.runner_subnet_id
}

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
  vpc_id      = local.runner_vpc_id

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

  # Fail closed on default-VPC placement (ADR-004-R20, issue #1222). A runner in
  # the account default VPC can have its AWS API resolution hijacked by a range's
  # private-DNS VPC endpoints. Place the runner in a dedicated runner VPC or the
  # portal VPC private tier instead. The account default VPC is permitted ONLY as
  # an explicit, documented opt-in via var.allow_default_vpc (ADR-004-R20 escape
  # hatch); when opted in, the range private-DNS collision risk is accepted for
  # that environment.
  lifecycle {
    precondition {
      condition     = var.allow_default_vpc || !contains(data.aws_vpcs.default.ids, local.runner_vpc_id)
      error_message = "github-runner: the runner VPC must not be the account default VPC unless var.allow_default_vpc = true (ADR-004-R20). Use a dedicated runner VPC or the portal VPC private tier, or set allow_default_vpc to accept default-VPC placement, so a range's private-DNS VPC endpoints cannot silently hijack the runner's AWS API resolution."
    }
    precondition {
      condition     = data.aws_subnet.runner.vpc_id == local.runner_vpc_id
      error_message = "github-runner: the runner subnet must belong to the runner VPC (ADR-004-R20); a subnet from another VPC is rejected."
    }
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

# IAM policy for the runner host-health monitor (#292) to publish CloudWatch
# metrics. cloudwatch:PutMetricData has no resource-level scoping, so least
# privilege is expressed through the cloudwatch:namespace condition, constraining
# it to the runner-specific Shifter/RunnerHealth namespace (distinct from
# Shifter/WorkerHealth so runner and worker alarms cannot cross-trip).
resource "aws_iam_role_policy" "cloudwatch_metrics" {
  name = "cloudwatch-metrics"
  role = aws_iam_role.runner.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["cloudwatch:PutMetricData"]
        Resource = "*"
        Condition = {
          StringEquals = {
            "cloudwatch:namespace" = "Shifter/RunnerHealth"
          }
        }
      }
    ]
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
  subnet_id              = local.runner_subnet_id
  iam_instance_profile   = aws_iam_instance_profile.runner.name

  root_block_device {
    volume_size = 50
    volume_type = "gp3"
  }

  # user_data is a first-boot-only path, so editing it does not run on an
  # already-running host. The health monitor (#292) lives in user_data, so
  # rolling it out to existing runners requires replacing them: this forces a
  # new instance whenever user_data changes, which re-runs the install. A
  # replaced runner must be re-registered (see README) - it is a "generated"
  # resource, so replacement is the accepted rollout mechanism.
  user_data_replace_on_change = true

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

    # --------------------------------------------------------------------------
    # Host-health monitor (#292)
    # --------------------------------------------------------------------------
    # Publish the runner systemd-service liveness to CloudWatch so a stopped
    # service - or a hung host that stops publishing entirely - surfaces as an
    # alarm instead of going silent. Artifacts are tracked under
    # runner-health/ and embedded via filebase64 to avoid heredoc escaping.
    echo '${filebase64("${path.module}/runner-health/shifter-runner-health.sh")}' | base64 -d > /usr/local/bin/shifter-runner-health.sh
    chmod 0755 /usr/local/bin/shifter-runner-health.sh
    echo '${filebase64("${path.module}/runner-health/shifter-runner-health.service")}' | base64 -d > /etc/systemd/system/shifter-runner-health.service
    echo '${filebase64("${path.module}/runner-health/shifter-runner-health.timer")}' | base64 -d > /etc/systemd/system/shifter-runner-health.timer

    # Per-runner metric dimension. This MUST be written before enabling the
    # timer: EnvironmentFile=- makes a missing file silent, so a wrong order
    # would make the first run emit under RunnerName=unknown.
    echo 'RUNNER_HEALTH_NAME=shifter-github-runner-${count.index + 1}' > /etc/shifter-runner-health.env

    systemctl daemon-reload
    systemctl enable --now shifter-runner-health.timer
  EOF
  )

  tags = {
    Name = "shifter-github-runner-${count.index + 1}"
  }
}
