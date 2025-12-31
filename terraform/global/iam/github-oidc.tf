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
# Managed IAM Policies (split to avoid size limits)
# ------------------------------------------------------------------------------

# Core Infrastructure: ECR, S3 state, DynamoDB locking
resource "aws_iam_policy" "core_infrastructure" {
  name = "shifter-${var.environment}-core-infrastructure"

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
      },
      {
        Sid    = "PulumiStateS3"
        Effect = "Allow"
        Action = [
          "s3:*"
        ]
        Resource = [
          "arn:aws:s3:::*-range-pulumi-state",
          "arn:aws:s3:::*-range-pulumi-state/*"
        ]
      },
      {
        Sid    = "PulumiStateDynamoDB"
        Effect = "Allow"
        Action = [
          "dynamodb:CreateTable",
          "dynamodb:DeleteTable",
          "dynamodb:DescribeTable",
          "dynamodb:UpdateTable",
          "dynamodb:DescribeTimeToLive",
          "dynamodb:UpdateTimeToLive",
          "dynamodb:ListTagsOfResource",
          "dynamodb:TagResource",
          "dynamodb:UntagResource",
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:DeleteItem",
          "dynamodb:DescribeContinuousBackups",
          "dynamodb:UpdateContinuousBackups"
        ]
        Resource = "arn:aws:dynamodb:${var.aws_region}:${data.aws_caller_identity.current.account_id}:table/*-range-pulumi-locks"
      }
    ]
  })
}

# VPC Networking
# checkov:skip=CKV_AWS_355:CI/CD requires broad VPC permissions for infrastructure management. Risk accepted, see #44
# checkov:skip=CKV_AWS_290:CI/CD requires broad VPC permissions for infrastructure management. Risk accepted, see #44
# checkov:skip=CKV_AWS_289:CI/CD requires broad VPC permissions for infrastructure management. Risk accepted, see #44
# checkov:skip=CKV_AWS_287:CI/CD requires broad VPC permissions for infrastructure management. Risk accepted, see #44
# NOTE: Not best practice. Project in rapid development - velocity impact of permissions errors
# and size of inline policies outweigh need for pure least privilege. Risk accepted.
resource "aws_iam_policy" "vpc_networking" {
  name = "shifter-${var.environment}-vpc-networking"

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
          "ec2:DeleteTags",
          "ec2:CreateFlowLogs",
          "ec2:DeleteFlowLogs",
          "ec2:DescribeFlowLogs"
        ]
        Resource = "*"
      }
    ]
  })
}

# EC2 Instances, Auto Scaling, and Launch Templates
# checkov:skip=CKV_AWS_355:CI/CD requires broad EC2 permissions for infrastructure management. Risk accepted, see #44
# checkov:skip=CKV_AWS_290:CI/CD requires broad EC2 permissions for infrastructure management. Risk accepted, see #44
# checkov:skip=CKV_AWS_289:CI/CD requires broad EC2 permissions for infrastructure management. Risk accepted, see #44
# checkov:skip=CKV_AWS_287:CI/CD requires broad EC2 permissions for infrastructure management. Risk accepted, see #44
# NOTE: Not best practice. Project in rapid development - velocity impact of permissions errors
# and size of inline policies outweigh need for pure least privilege. Risk accepted.
resource "aws_iam_policy" "ec2_instances" {
  name = "shifter-${var.environment}-ec2-instances"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      # TODO: Scope down EC2 permissions - see GitHub issue for audit
      {
        Sid      = "EC2"
        Effect   = "Allow"
        Action   = ["ec2:*"]
        Resource = "*"
      },
      {
        Sid    = "AutoScaling"
        Effect = "Allow"
        Action = [
          "autoscaling:CreateAutoScalingGroup",
          "autoscaling:DeleteAutoScalingGroup",
          "autoscaling:DescribeAutoScalingGroups",
          "autoscaling:UpdateAutoScalingGroup",
          "autoscaling:CreateLaunchConfiguration",
          "autoscaling:DeleteLaunchConfiguration",
          "autoscaling:DescribeLaunchConfigurations",
          "autoscaling:CreateOrUpdateTags",
          "autoscaling:DeleteTags",
          "autoscaling:DescribeTags",
          "autoscaling:PutScalingPolicy",
          "autoscaling:DeletePolicy",
          "autoscaling:DescribePolicies",
          "autoscaling:SetDesiredCapacity",
          "autoscaling:TerminateInstanceInAutoScalingGroup",
          "autoscaling:StartInstanceRefresh",
          "autoscaling:DescribeInstanceRefreshes",
          "autoscaling:DescribeScalingActivities"
        ]
        Resource = "*"
      }
    ]
  })
}

# ELB and ACM
# checkov:skip=CKV_AWS_355:CI/CD requires broad ELB/ACM permissions for infrastructure management. Risk accepted, see #44
# checkov:skip=CKV_AWS_290:CI/CD requires broad ELB/ACM permissions for infrastructure management. Risk accepted, see #44
# checkov:skip=CKV_AWS_289:CI/CD requires broad ELB/ACM permissions for infrastructure management. Risk accepted, see #44
# checkov:skip=CKV_AWS_287:CI/CD requires broad ELB/ACM permissions for infrastructure management. Risk accepted, see #44
# NOTE: Not best practice. Project in rapid development - velocity impact of permissions errors
# and size of inline policies outweigh need for pure least privilege. Risk accepted.
# checkov:skip=CKV_AWS_355:CI/CD requires WAFv2 permissions. Risk accepted, see #44
# checkov:skip=CKV_AWS_290:CI/CD requires WAFv2 permissions. Risk accepted, see #44
# checkov:skip=CKV_AWS_289:CI/CD requires WAFv2 permissions. Risk accepted, see #44
# checkov:skip=CKV_AWS_287:CI/CD requires WAFv2 permissions. Risk accepted, see #44
resource "aws_iam_policy" "elb_acm" {
  name = "shifter-${var.environment}-elb-acm"

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
      },
      {
        Sid    = "WAFv2"
        Effect = "Allow"
        Action = [
          "wafv2:CreateWebACL",
          "wafv2:DeleteWebACL",
          "wafv2:GetWebACL",
          "wafv2:UpdateWebACL",
          "wafv2:ListWebACLs",
          "wafv2:AssociateWebACL",
          "wafv2:DisassociateWebACL",
          "wafv2:GetWebACLForResource",
          "wafv2:ListResourcesForWebACL",
          "wafv2:ListTagsForResource",
          "wafv2:TagResource",
          "wafv2:UntagResource",
          "wafv2:DescribeManagedRuleGroup",
          "wafv2:ListAvailableManagedRuleGroups"
        ]
        Resource = "*"
      }
    ]
  })
}

# IAM Scoped (roles and instance profiles)
# Restricted to specific naming patterns to limit blast radius if GitHub Actions is compromised.
# See issue #430 for planned migration to consistent shifter-* naming.
resource "aws_iam_policy" "iam_scoped" {
  name = "shifter-${var.environment}-iam-scoped"

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
        Resource = [
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/dev-portal-*",
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/prod-portal-*",
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/dev-range-*",
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/prod-range-*",
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/shifter-*",
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/github-actions-shifter-*"
        ]
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
        Resource = [
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:instance-profile/dev-portal-*",
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:instance-profile/prod-portal-*",
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:instance-profile/dev-range-*",
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:instance-profile/prod-range-*",
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:instance-profile/shifter-*",
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:instance-profile/github-actions-shifter-*"
        ]
      },
      {
        Sid    = "IAMPassRole"
        Effect = "Allow"
        Action = ["iam:PassRole"]
        Resource = [
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/dev-portal-*",
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/prod-portal-*",
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/dev-range-*",
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/prod-range-*",
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/shifter-*",
          "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/github-actions-shifter-*"
        ]
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
  name = "shifter-${var.environment}-lambda-sfn"

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
          "logs:UntagResource",
          "logs:CreateLogDelivery",
          "logs:DeleteLogDelivery",
          "logs:GetLogDelivery",
          "logs:ListLogDeliveries",
          "logs:UpdateLogDelivery",
          "logs:PutResourcePolicy",
          "logs:DescribeResourcePolicies",
          "logs:DescribeLogGroups"
        ]
        Resource = "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:*"
      },
      {
        Sid    = "CloudWatchLogsGlobal"
        Effect = "Allow"
        Action = [
          "logs:CreateLogDelivery",
          "logs:DeleteLogDelivery",
          "logs:GetLogDelivery",
          "logs:ListLogDeliveries",
          "logs:UpdateLogDelivery",
          "logs:PutResourcePolicy",
          "logs:DescribeResourcePolicies",
          "logs:DescribeLogGroups"
        ]
        Resource = "*"
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
        Resource = [
          "arn:aws:sns:${var.aws_region}:${data.aws_caller_identity.current.account_id}:*-portal-*",
          "arn:aws:sns:${var.aws_region}:${data.aws_caller_identity.current.account_id}:*-range-*"
        ]
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
      },
      {
        Sid    = "ECS"
        Effect = "Allow"
        Action = [
          "ecs:*"
        ]
        Resource = "*"
      }
    ]
  })
}

# RDS and ElastiCache (managed data stores)
# checkov:skip=CKV_AWS_355:CI/CD requires broad RDS/ElastiCache permissions. Risk accepted, see #44
# checkov:skip=CKV_AWS_290:CI/CD requires broad RDS/ElastiCache permissions. Risk accepted, see #44
# checkov:skip=CKV_AWS_289:CI/CD requires broad RDS/ElastiCache permissions. Risk accepted, see #44
# checkov:skip=CKV_AWS_287:CI/CD requires broad RDS/ElastiCache permissions. Risk accepted, see #44
# NOTE: Not best practice. Project in rapid development - velocity impact of permissions errors
# and size of inline policies outweigh need for pure least privilege. Risk accepted.
resource "aws_iam_policy" "rds" {
  name = "shifter-${var.environment}-rds"

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
      },
      {
        Sid    = "ElastiCache"
        Effect = "Allow"
        Action = [
          "elasticache:CreateCacheCluster",
          "elasticache:DeleteCacheCluster",
          "elasticache:DescribeCacheClusters",
          "elasticache:ModifyCacheCluster",
          "elasticache:CreateCacheSubnetGroup",
          "elasticache:DeleteCacheSubnetGroup",
          "elasticache:DescribeCacheSubnetGroups",
          "elasticache:ModifyCacheSubnetGroup",
          "elasticache:DescribeCacheParameterGroups",
          "elasticache:DescribeCacheParameters",
          "elasticache:DescribeEngineDefaultParameters",
          "elasticache:AddTagsToResource",
          "elasticache:RemoveTagsFromResource",
          "elasticache:ListTagsForResource"
        ]
        Resource = "*"
      }
    ]
  })
}

# Secrets Manager and KMS
# checkov:skip=CKV_AWS_355:CI/CD requires broad Secrets/KMS permissions. Risk accepted, see #44
# checkov:skip=CKV_AWS_290:CI/CD requires broad Secrets/KMS permissions. Risk accepted, see #44
# checkov:skip=CKV_AWS_289:CI/CD requires broad Secrets/KMS permissions. Risk accepted, see #44
# checkov:skip=CKV_AWS_287:CI/CD requires broad Secrets/KMS permissions. Risk accepted, see #44
# NOTE: Not best practice. Project in rapid development - velocity impact of permissions errors
# and size of inline policies outweigh need for pure least privilege. Risk accepted.
resource "aws_iam_policy" "secrets_kms" {
  name = "shifter-${var.environment}-secrets-kms"

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
          "kms:ScheduleKeyDeletion",
          "kms:GetKeyPolicy",
          "kms:PutKeyPolicy",
          "kms:EnableKeyRotation",
          "kms:GetKeyRotationStatus"
        ]
        Resource = "*"
      }
    ]
  })
}

# SSM and Cognito
# checkov:skip=CKV_AWS_355:CI/CD requires broad SSM/Cognito permissions. Risk accepted, see #44
# checkov:skip=CKV_AWS_290:CI/CD requires broad SSM/Cognito permissions. Risk accepted, see #44
# checkov:skip=CKV_AWS_289:CI/CD requires broad SSM/Cognito permissions. Risk accepted, see #44
# checkov:skip=CKV_AWS_287:CI/CD requires broad SSM/Cognito permissions. Risk accepted, see #44
# NOTE: Not best practice. Project in rapid development - velocity impact of permissions errors
# and size of inline policies outweigh need for pure least privilege. Risk accepted.
resource "aws_iam_policy" "ssm_cognito" {
  name = "shifter-${var.environment}-ssm-cognito"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "SSMRunCommand"
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
        Sid    = "SSMParameterStore"
        Effect = "Allow"
        Action = [
          "ssm:PutParameter",
          "ssm:GetParameter",
          "ssm:GetParameters",
          "ssm:DeleteParameter",
          "ssm:DescribeParameters",
          "ssm:AddTagsToResource",
          "ssm:RemoveTagsFromResource",
          "ssm:ListTagsForResource"
        ]
        Resource = [
          # Range parameters for DC config
          "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter/shifter/*/range/*",
          # AMI IDs for Kali, victim, windows, dc
          "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter/shifter/ami/*"
        ]
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

# Network Firewall
# checkov:skip=CKV_AWS_355:CI/CD requires Network Firewall permissions. Risk accepted, see #44
# checkov:skip=CKV_AWS_290:CI/CD requires Network Firewall permissions. Risk accepted, see #44
# checkov:skip=CKV_AWS_289:CI/CD requires Network Firewall permissions. Risk accepted, see #44
# checkov:skip=CKV_AWS_287:CI/CD requires Network Firewall permissions. Risk accepted, see #44
resource "aws_iam_policy" "network_firewall" {
  name = "shifter-${var.environment}-network-firewall"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "NetworkFirewall"
        Effect = "Allow"
        Action = [
          "network-firewall:CreateFirewall",
          "network-firewall:DeleteFirewall",
          "network-firewall:DescribeFirewall",
          "network-firewall:UpdateFirewallDeleteProtection",
          "network-firewall:UpdateFirewallDescription",
          "network-firewall:UpdateFirewallPolicy",
          "network-firewall:UpdateFirewallPolicyChangeProtection",
          "network-firewall:UpdateSubnetChangeProtection",
          "network-firewall:AssociateFirewallPolicy",
          "network-firewall:DisassociateSubnets",
          "network-firewall:AssociateSubnets",
          "network-firewall:CreateFirewallPolicy",
          "network-firewall:DeleteFirewallPolicy",
          "network-firewall:DescribeFirewallPolicy",
          "network-firewall:UpdateFirewallPolicy",
          "network-firewall:CreateRuleGroup",
          "network-firewall:DeleteRuleGroup",
          "network-firewall:DescribeRuleGroup",
          "network-firewall:UpdateRuleGroup",
          "network-firewall:ListFirewalls",
          "network-firewall:ListFirewallPolicies",
          "network-firewall:ListRuleGroups",
          "network-firewall:TagResource",
          "network-firewall:UntagResource",
          "network-firewall:ListTagsForResource",
          "network-firewall:DescribeLoggingConfiguration",
          "network-firewall:UpdateLoggingConfiguration"
        ]
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

resource "aws_iam_role_policy_attachment" "network_firewall" {
  role       = aws_iam_role.github_actions.name
  policy_arn = aws_iam_policy.network_firewall.arn
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
