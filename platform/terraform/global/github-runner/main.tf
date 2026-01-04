# ------------------------------------------------------------------------------
# GitHub Actions Self-Hosted Runner (Auto-Scaling)
# ------------------------------------------------------------------------------
# Uses the terraform-aws-github-runner module for auto-scaling, ephemeral runners.
# Runners scale from 0 when idle and auto-register via GitHub App authentication.
# ------------------------------------------------------------------------------

terraform {
  required_version = ">= 1.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.0"
    }
  }

  backend "s3" {}
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

# ------------------------------------------------------------------------------
# Data Sources
# ------------------------------------------------------------------------------

data "aws_caller_identity" "current" {}

# Get default VPC subnets for runner placement
data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [var.vpc_id]
  }
}

# Fetch GitHub App secrets from SSM Parameter Store
data "aws_ssm_parameter" "github_app_key" {
  name            = var.github_app_key_ssm_path
  with_decryption = true
}

data "aws_ssm_parameter" "github_app_webhook_secret" {
  name            = var.github_app_webhook_secret_ssm_path
  with_decryption = true
}

# ------------------------------------------------------------------------------
# Random suffix for unique resource naming
# ------------------------------------------------------------------------------

resource "random_id" "suffix" {
  byte_length = 4
}

# ------------------------------------------------------------------------------
# Download Lambda Functions from GitHub Releases
# ------------------------------------------------------------------------------

module "lambdas" {
  source  = "github-aws-runners/github-runner/aws//modules/download-lambda"
  version = "~> 5.0"

  lambdas = [
    {
      name = "webhook"
      tag  = "v5.21.0"
    },
    {
      name = "runners"
      tag  = "v5.21.0"
    },
    {
      name = "runner-binaries-syncer"
      tag  = "v5.21.0"
    }
  ]
}

# ------------------------------------------------------------------------------
# IAM Policy for ECR Access (Docker builds)
# ------------------------------------------------------------------------------

resource "aws_iam_policy" "runner_ecr" {
  name        = "shifter-runner-ecr-access"
  description = "ECR access for GitHub Actions runner Docker builds"

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
          "ecr:BatchGetImage",
          "ecr:PutImage",
          "ecr:InitiateLayerUpload",
          "ecr:UploadLayerPart",
          "ecr:CompleteLayerUpload"
        ]
        Resource = "arn:aws:ecr:${var.region}:${data.aws_caller_identity.current.account_id}:repository/shifter-*"
      }
    ]
  })
}

# ------------------------------------------------------------------------------
# GitHub Actions Runner Module
# ------------------------------------------------------------------------------

module "github_runner" {
  source  = "github-aws-runners/github-runner/aws"
  version = "~> 5.0"

  prefix = "shifter-${var.environment}"

  # AWS Configuration
  aws_region = var.region
  vpc_id     = var.vpc_id
  subnet_ids = data.aws_subnets.default.ids

  # GitHub App Configuration
  github_app = {
    id             = var.github_app_id
    key_base64     = data.aws_ssm_parameter.github_app_key.value
    webhook_secret = data.aws_ssm_parameter.github_app_webhook_secret.value
  }

  # Lambda zip files from download module
  # Order matches lambdas list: [0]=webhook, [1]=runners, [2]=runner-binaries-syncer
  webhook_lambda_zip                = module.lambdas.files[0]
  runners_lambda_zip                = module.lambdas.files[1]
  runner_binaries_syncer_lambda_zip = module.lambdas.files[2]

  # Runner Configuration
  enable_organization_runners = true
  runner_extra_labels         = ["shifter", var.environment]

  # Runner scaling configuration
  runners_maximum_count          = var.runners_maximum_count
  scale_down_schedule_expression = "cron(*/5 * * * ? *)" # Check every 5 minutes

  # Instance configuration
  instance_types = var.instance_types

  # Enable spot instances for cost savings
  instance_target_capacity_type = "spot"

  # Runner OS and architecture
  runner_os           = "linux"
  runner_architecture = "x64"

  # Ephemeral runners (recommended for security)
  enable_ephemeral_runners = true

  # Enable SSM for debugging access
  enable_ssm_on_runners = true

  # Additional IAM policies for runner instances
  runner_iam_role_managed_policy_arns = [
    aws_iam_policy.runner_ecr.arn
  ]

  # Logging
  logging_retention_in_days = 14

  # Tags
  tags = {
    Environment = var.environment
  }
}
