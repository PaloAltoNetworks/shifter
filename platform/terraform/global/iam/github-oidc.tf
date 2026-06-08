variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-2"
}

variable "environment" {
  description = "Environment name (dev or prod)"
  type        = string
  validation {
    condition     = contains(["dev", "prod"], var.environment)
    error_message = "Environment must be 'dev' or 'prod'."
  }
}

variable "github_org" {
  description = "GitHub organization"
  type        = string
  default     = "Brad-Edwards"
}

variable "github_repo" {
  description = "GitHub repository name"
  type        = string
  default     = "shifter"
}

# Get current AWS account ID
data "aws_caller_identity" "current" {}

# GitHub OIDC Provider
resource "aws_iam_openid_connect_provider" "github" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1", "1b511abead59c6ce207077c0bf0e0043b1382612"]

  tags = {
    Name    = "github-actions-oidc"
    Project = "shifter"
  }
}

# IAM Role for GitHub Actions
resource "aws_iam_role" "github_actions" {
  name = "github-actions-shifter-${var.environment}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Federated = aws_iam_openid_connect_provider.github.arn
        }
        Action = "sts:AssumeRoleWithWebIdentity"
        Condition = {
          StringEquals = {
            "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
          }
          StringLike = {
            "token.actions.githubusercontent.com:sub" = "repo:${var.github_org}/${var.github_repo}:*"
          }
        }
      }
    ]
  })

  tags = {
    Name        = "github-actions-shifter-${var.environment}"
    Project     = "shifter"
    Environment = var.environment
  }
}

# ------------------------------------------------------------------------------
# AWS Role Policy
# Full access during rapid development.
# TODO: Scope down to least privilege before production hardening.
# ------------------------------------------------------------------------------

resource "aws_iam_role_policy" "admin" {
  # checkov:skip=CKV_AWS_274:Dev deploy role is admin-equivalent. See ADR-004-R11 exception aws-dev-bootstrap-inline-admin.
  # checkov:skip=CKV_AWS_288:Dev deploy role is admin-equivalent. See ADR-004-R11 exception aws-dev-bootstrap-inline-admin.
  # checkov:skip=CKV_AWS_286:Dev deploy role is admin-equivalent. See ADR-004-R11 exception aws-dev-bootstrap-inline-admin.
  # checkov:skip=CKV_AWS_62:Dev deploy role is admin-equivalent. See ADR-004-R11 exception aws-dev-bootstrap-inline-admin.
  # checkov:skip=CKV_AWS_63:Dev deploy role is admin-equivalent. See ADR-004-R11 exception aws-dev-bootstrap-inline-admin.
  # checkov:skip=CKV_AWS_287:Dev deploy role is admin-equivalent. See ADR-004-R11 exception aws-dev-bootstrap-inline-admin.
  # checkov:skip=CKV2_AWS_40:Dev deploy role is admin-equivalent. See ADR-004-R11 exception aws-dev-bootstrap-inline-admin.

  name = "administrator-access"
  role = aws_iam_role.github_actions.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "*"
        Resource = "*"
      }
    ]
  })
}

# ------------------------------------------------------------------------------
# Outputs
# ------------------------------------------------------------------------------

output "github_actions_role_arn" {
  description = "ARN of the IAM role for GitHub Actions (add to GitHub secrets as AWS_ROLE_ARN)"
  value       = aws_iam_role.github_actions.arn
}

output "oidc_provider_arn" {
  description = "ARN of the GitHub OIDC provider"
  value       = aws_iam_openid_connect_provider.github.arn
}
