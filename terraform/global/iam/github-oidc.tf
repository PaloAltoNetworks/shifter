terraform {
  required_version = ">= 1.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-2"
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
  name = "github-actions-shifter"

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
    Name    = "github-actions-shifter"
    Project = "shifter"
  }
}

# ------------------------------------------------------------------------------
# Managed IAM Policies (split to avoid size limits)
# ------------------------------------------------------------------------------

# Core Infrastructure: ECR, S3 state, DynamoDB locking
resource "aws_iam_policy" "core_infrastructure" {
  name = "shifter-core-infrastructure"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ECR"
        Effect   = "Allow"
        Action   = ["ecr:*"]
        Resource = "arn:aws:ecr:${var.aws_region}:${data.aws_caller_identity.current.account_id}:repository/shifter-*"
      },
      {
        Sid      = "ECRAuth"
        Effect   = "Allow"
        Action   = ["ecr:GetAuthorizationToken"]
        Resource = "*"
      },
      {
        Sid    = "S3State"
        Effect = "Allow"
        Action = [
          "s3:ListBucket",
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject"
        ]
        Resource = [
          "arn:aws:s3:::shifter-infra-*",
          "arn:aws:s3:::shifter-infra-*/*"
        ]
      },
      {
        Sid      = "S3UserStorage"
        Effect   = "Allow"
        Action   = ["s3:*"]
        Resource = "arn:aws:s3:::shifter-user-storage-*"
      },
      {
        Sid    = "DynamoDB"
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:DeleteItem"
        ]
        Resource = "arn:aws:dynamodb:${var.aws_region}:${data.aws_caller_identity.current.account_id}:table/shifter-terraform-*"
      }
    ]
  })
}

# VPC Networking
resource "aws_iam_policy" "vpc_networking" {
  name = "shifter-vpc-networking"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "VPC"
        Effect = "Allow"
        Action = [
          "ec2:*Vpc*",
          "ec2:*Subnet*",
          "ec2:*RouteTable*",
          "ec2:*Route",
          "ec2:*InternetGateway*",
          "ec2:*NatGateway*",
          "ec2:*Address*",
          "ec2:*SecurityGroup*",
          "ec2:*Tags",
          "ec2:Describe*",
          "ec2:CreateTags",
          "ec2:DeleteTags"
        ]
        Resource = "*"
      }
    ]
  })
}

# EC2 Instances
resource "aws_iam_policy" "ec2_instances" {
  name = "shifter-ec2-instances"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "EC2"
        Effect = "Allow"
        Action = [
          "ec2:RunInstances",
          "ec2:TerminateInstances",
          "ec2:StartInstances",
          "ec2:StopInstances",
          "ec2:RebootInstances",
          "ec2:DescribeInstances",
          "ec2:DescribeInstanceStatus",
          "ec2:DescribeInstanceTypes",
          "ec2:DescribeInstanceAttribute",
          "ec2:ModifyInstanceAttribute",
          "ec2:DescribeImages",
          "ec2:DescribeVolumes",
          "ec2:CreateVolume",
          "ec2:DeleteVolume",
          "ec2:AttachVolume",
          "ec2:DetachVolume",
          "ec2:DescribeInstanceCreditSpecifications",
          "ec2:DescribeKeyPairs",
          "ec2:CreateKeyPair",
          "ec2:DeleteKeyPair"
        ]
        Resource = "*"
      }
    ]
  })
}

# ELB and ACM
resource "aws_iam_policy" "elb_acm" {
  name = "shifter-elb-acm"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ELB"
        Effect   = "Allow"
        Action   = ["elasticloadbalancing:*"]
        Resource = "*"
      },
      {
        Sid      = "ACM"
        Effect   = "Allow"
        Action   = ["acm:*"]
        Resource = "*"
      }
    ]
  })
}

# IAM Scoped (roles and instance profiles)
resource "aws_iam_policy" "iam_scoped" {
  name = "shifter-iam-scoped"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "IAMRoles"
        Effect = "Allow"
        Action = [
          "iam:CreateRole",
          "iam:DeleteRole",
          "iam:GetRole",
          "iam:UpdateRole",
          "iam:TagRole",
          "iam:UntagRole",
          "iam:ListRolePolicies",
          "iam:ListAttachedRolePolicies",
          "iam:ListInstanceProfilesForRole",
          "iam:PutRolePolicy",
          "iam:GetRolePolicy",
          "iam:DeleteRolePolicy",
          "iam:AttachRolePolicy",
          "iam:DetachRolePolicy"
        ]
        Resource = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/*"
      },
      {
        Sid    = "IAMInstanceProfiles"
        Effect = "Allow"
        Action = [
          "iam:CreateInstanceProfile",
          "iam:DeleteInstanceProfile",
          "iam:GetInstanceProfile",
          "iam:AddRoleToInstanceProfile",
          "iam:RemoveRoleFromInstanceProfile",
          "iam:TagInstanceProfile",
          "iam:UntagInstanceProfile"
        ]
        Resource = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:instance-profile/*"
      },
      {
        Sid      = "IAMPassRole"
        Effect   = "Allow"
        Action   = ["iam:PassRole"]
        Resource = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/*"
      },
      {
        Sid      = "IAMServiceLinkedRoles"
        Effect   = "Allow"
        Action   = ["iam:CreateServiceLinkedRole"]
        Resource = "arn:aws:iam::*:role/aws-service-role/*"
      }
    ]
  })
}

# Lambda and Step Functions
resource "aws_iam_policy" "lambda_sfn" {
  name = "shifter-lambda-sfn"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "Lambda"
        Effect = "Allow"
        Action = [
          "lambda:CreateFunction",
          "lambda:DeleteFunction",
          "lambda:GetFunction",
          "lambda:GetFunctionConfiguration",
          "lambda:GetFunctionCodeSigningConfig",
          "lambda:UpdateFunctionCode",
          "lambda:UpdateFunctionConfiguration",
          "lambda:ListVersionsByFunction",
          "lambda:PublishVersion",
          "lambda:AddPermission",
          "lambda:RemovePermission",
          "lambda:GetPolicy",
          "lambda:TagResource",
          "lambda:UntagResource",
          "lambda:ListTags"
        ]
        Resource = "arn:aws:lambda:${var.aws_region}:${data.aws_caller_identity.current.account_id}:function:*"
      },
      {
        Sid    = "LambdaLayers"
        Effect = "Allow"
        Action = [
          "lambda:PublishLayerVersion",
          "lambda:GetLayerVersion",
          "lambda:DeleteLayerVersion",
          "lambda:ListLayerVersions"
        ]
        Resource = "arn:aws:lambda:${var.aws_region}:${data.aws_caller_identity.current.account_id}:layer:*"
      },
      {
        Sid    = "StepFunctions"
        Effect = "Allow"
        Action = [
          "states:CreateStateMachine",
          "states:DeleteStateMachine",
          "states:DescribeStateMachine",
          "states:UpdateStateMachine",
          "states:ListStateMachines",
          "states:TagResource",
          "states:UntagResource",
          "states:ListTagsForResource"
        ]
        Resource = "arn:aws:states:${var.aws_region}:${data.aws_caller_identity.current.account_id}:stateMachine:*"
      },
      {
        Sid    = "CloudWatchLogs"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:DeleteLogGroup",
          "logs:DescribeLogGroups",
          "logs:PutRetentionPolicy",
          "logs:TagLogGroup",
          "logs:UntagLogGroup",
          "logs:ListTagsLogGroup",
          "logs:ListTagsForResource",
          "logs:TagResource",
          "logs:UntagResource"
        ]
        Resource = "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:*"
      },
      {
        Sid    = "CloudWatchAlarms"
        Effect = "Allow"
        Action = [
          "cloudwatch:PutMetricAlarm",
          "cloudwatch:DeleteAlarms",
          "cloudwatch:DescribeAlarms",
          "cloudwatch:ListTagsForResource",
          "cloudwatch:TagResource",
          "cloudwatch:UntagResource"
        ]
        Resource = "arn:aws:cloudwatch:${var.aws_region}:${data.aws_caller_identity.current.account_id}:alarm:*"
      },
      {
        Sid    = "SNS"
        Effect = "Allow"
        Action = [
          "sns:CreateTopic",
          "sns:DeleteTopic",
          "sns:GetTopicAttributes",
          "sns:SetTopicAttributes",
          "sns:ListTagsForResource",
          "sns:TagResource",
          "sns:UntagResource",
          "sns:Subscribe",
          "sns:Unsubscribe",
          "sns:GetSubscriptionAttributes"
        ]
        Resource = "arn:aws:sns:${var.aws_region}:${data.aws_caller_identity.current.account_id}:*-portal-*"
      },
      {
        Sid    = "EventBridge"
        Effect = "Allow"
        Action = [
          "events:PutRule",
          "events:DeleteRule",
          "events:DescribeRule",
          "events:EnableRule",
          "events:DisableRule",
          "events:PutTargets",
          "events:RemoveTargets",
          "events:ListTargetsByRule",
          "events:ListTagsForResource",
          "events:TagResource",
          "events:UntagResource"
        ]
        Resource = "arn:aws:events:${var.aws_region}:${data.aws_caller_identity.current.account_id}:rule/*-portal-*"
      }
    ]
  })
}

# RDS
resource "aws_iam_policy" "rds" {
  name = "shifter-rds"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "RDS"
        Effect = "Allow"
        Action = [
          "rds:CreateDBInstance",
          "rds:DeleteDBInstance",
          "rds:DescribeDBInstances",
          "rds:ModifyDBInstance",
          "rds:RebootDBInstance",
          "rds:StartDBInstance",
          "rds:StopDBInstance",
          "rds:CreateDBSubnetGroup",
          "rds:DeleteDBSubnetGroup",
          "rds:DescribeDBSubnetGroups",
          "rds:ModifyDBSubnetGroup",
          "rds:CreateDBParameterGroup",
          "rds:DeleteDBParameterGroup",
          "rds:DescribeDBParameterGroups",
          "rds:ModifyDBParameterGroup",
          "rds:DescribeDBParameters",
          "rds:AddTagsToResource",
          "rds:RemoveTagsFromResource",
          "rds:ListTagsForResource",
          "rds:DescribeDBEngineVersions",
          "rds:DescribeOrderableDBInstanceOptions"
        ]
        Resource = "*"
      }
    ]
  })
}

# Secrets Manager and KMS
resource "aws_iam_policy" "secrets_kms" {
  name = "shifter-secrets-kms"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "SecretsManager"
        Effect = "Allow"
        Action = [
          "secretsmanager:CreateSecret",
          "secretsmanager:DeleteSecret",
          "secretsmanager:DescribeSecret",
          "secretsmanager:GetSecretValue",
          "secretsmanager:PutSecretValue",
          "secretsmanager:UpdateSecret",
          "secretsmanager:TagResource",
          "secretsmanager:UntagResource",
          "secretsmanager:GetResourcePolicy",
          "secretsmanager:PutResourcePolicy",
          "secretsmanager:DeleteResourcePolicy"
        ]
        Resource = "arn:aws:secretsmanager:${var.aws_region}:${data.aws_caller_identity.current.account_id}:secret:shifter-*"
      },
      {
        Sid      = "SecretsManagerRandom"
        Effect   = "Allow"
        Action   = ["secretsmanager:GetRandomPassword"]
        Resource = "*"
      },
      {
        Sid    = "KMS"
        Effect = "Allow"
        Action = [
          "kms:CreateKey",
          "kms:DescribeKey",
          "kms:CreateAlias",
          "kms:DeleteAlias",
          "kms:ListAliases",
          "kms:Encrypt",
          "kms:Decrypt",
          "kms:GenerateDataKey",
          "kms:TagResource",
          "kms:UntagResource",
          "kms:ScheduleKeyDeletion"
        ]
        Resource = "*"
      }
    ]
  })
}

# SSM and Cognito
resource "aws_iam_policy" "ssm_cognito" {
  name = "shifter-ssm-cognito"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "SSM"
        Effect = "Allow"
        Action = [
          "ssm:SendCommand",
          "ssm:GetCommandInvocation",
          "ssm:ListCommandInvocations",
          "ssm:DescribeInstanceInformation"
        ]
        Resource = "*"
      },
      {
        Sid      = "Cognito"
        Effect   = "Allow"
        Action   = ["cognito-idp:*"]
        Resource = "*"
      }
    ]
  })
}

# ------------------------------------------------------------------------------
# Policy Attachments
# ------------------------------------------------------------------------------

resource "aws_iam_role_policy_attachment" "core_infrastructure" {
  role       = aws_iam_role.github_actions.name
  policy_arn = aws_iam_policy.core_infrastructure.arn
}

resource "aws_iam_role_policy_attachment" "vpc_networking" {
  role       = aws_iam_role.github_actions.name
  policy_arn = aws_iam_policy.vpc_networking.arn
}

resource "aws_iam_role_policy_attachment" "ec2_instances" {
  role       = aws_iam_role.github_actions.name
  policy_arn = aws_iam_policy.ec2_instances.arn
}

resource "aws_iam_role_policy_attachment" "elb_acm" {
  role       = aws_iam_role.github_actions.name
  policy_arn = aws_iam_policy.elb_acm.arn
}

resource "aws_iam_role_policy_attachment" "iam_scoped" {
  role       = aws_iam_role.github_actions.name
  policy_arn = aws_iam_policy.iam_scoped.arn
}

resource "aws_iam_role_policy_attachment" "lambda_sfn" {
  role       = aws_iam_role.github_actions.name
  policy_arn = aws_iam_policy.lambda_sfn.arn
}

resource "aws_iam_role_policy_attachment" "rds" {
  role       = aws_iam_role.github_actions.name
  policy_arn = aws_iam_policy.rds.arn
}

resource "aws_iam_role_policy_attachment" "secrets_kms" {
  role       = aws_iam_role.github_actions.name
  policy_arn = aws_iam_policy.secrets_kms.arn
}

resource "aws_iam_role_policy_attachment" "ssm_cognito" {
  role       = aws_iam_role.github_actions.name
  policy_arn = aws_iam_policy.ssm_cognito.arn
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
