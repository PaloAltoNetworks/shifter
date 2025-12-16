# Provisioner Lambda IAM Configuration
#
# Creates an execution role with:
# - rds-db:connect for IAM Database Authentication
# - EC2 permissions scoped to Range VPC only
# - CloudWatch Logs permissions
# - S3 read access for agent installers
#
# Also creates an instance profile for range EC2s (victim/kali) with:
# - SSM managed instance core policy for Systems Manager access

data "aws_region" "current" {}
data "aws_caller_identity" "current" {}

# ------------------------------------------------------------------------------
# Range Instance IAM Role (for Victim and Kali EC2s)
# ------------------------------------------------------------------------------

resource "aws_iam_role" "range_instance" {
  name = "${var.name_prefix}-range-instance"

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

  tags = merge(var.tags, {
    Name   = "${var.name_prefix}-range-instance"
    Module = "provisioner"
  })
}

resource "aws_iam_role_policy_attachment" "range_instance_ssm" {
  role       = aws_iam_role.range_instance.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "range_instance" {
  name = "${var.name_prefix}-range-instance"
  role = aws_iam_role.range_instance.name

  tags = merge(var.tags, {
    Name   = "${var.name_prefix}-range-instance"
    Module = "provisioner"
  })
}

# ------------------------------------------------------------------------------
# Lambda Execution Role
# ------------------------------------------------------------------------------

resource "aws_iam_role" "lambda" {
  name = "${var.name_prefix}-provisioner-lambda"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })

  tags = merge(var.tags, {
    Name   = "${var.name_prefix}-provisioner-lambda"
    Module = "provisioner"
  })
}

# ------------------------------------------------------------------------------
# CloudWatch Logs Policy
# ------------------------------------------------------------------------------

resource "aws_iam_role_policy" "lambda_logs" {
  name = "cloudwatch-logs"
  role = aws_iam_role.lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/${var.name_prefix}-*"
      }
    ]
  })
}

# ------------------------------------------------------------------------------
# VPC Access Policy (for Lambda in VPC)
# ------------------------------------------------------------------------------

resource "aws_iam_role_policy" "lambda_vpc" {
  name = "vpc-access"
  role = aws_iam_role.lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "ec2:CreateNetworkInterface",
          "ec2:DescribeNetworkInterfaces",
          "ec2:DeleteNetworkInterface",
          "ec2:AssignPrivateIpAddresses",
          "ec2:UnassignPrivateIpAddresses"
        ]
        Resource = "*"
      }
    ]
  })
}

# ------------------------------------------------------------------------------
# RDS IAM Database Authentication Policy
# ------------------------------------------------------------------------------

resource "aws_iam_role_policy" "lambda_rds" {
  name = "rds-iam-auth"
  role = aws_iam_role.lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "rds-db:connect"
        Resource = "arn:aws:rds-db:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:dbuser:${var.db_resource_id}/provisioner_lambda"
      }
    ]
  })
}

# ------------------------------------------------------------------------------
# EC2 Permissions - Scoped to Range VPC Only
# ------------------------------------------------------------------------------

resource "aws_iam_role_policy" "lambda_ec2" {
  name = "ec2-range-vpc"
  role = aws_iam_role.lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      # Describe operations (needed to check state)
      {
        Effect = "Allow"
        Action = [
          "ec2:DescribeSubnets",
          "ec2:DescribeInstances",
          "ec2:DescribeRouteTables",
          "ec2:DescribeSecurityGroups",
          "ec2:DescribeVpcs"
        ]
        Resource = "*"
      },
      # Subnet operations - scoped to Range VPC
      {
        Effect = "Allow"
        Action = [
          "ec2:CreateSubnet",
          "ec2:DeleteSubnet",
          "ec2:ModifySubnetAttribute"
        ]
        Resource = [
          "arn:aws:ec2:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:subnet/*",
          "arn:aws:ec2:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:vpc/${var.range_vpc_id}"
        ]
      },
      # Route table association
      {
        Effect = "Allow"
        Action = [
          "ec2:AssociateRouteTable",
          "ec2:DisassociateRouteTable"
        ]
        Resource = "*"
      },
      # Instance operations - must be tagged
      {
        Effect = "Allow"
        Action = "ec2:RunInstances"
        Resource = [
          "arn:aws:ec2:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:subnet/*",
          "arn:aws:ec2:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:security-group/*",
          "arn:aws:ec2:${data.aws_region.current.name}::image/*",
          "arn:aws:ec2:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:network-interface/*",
          "arn:aws:ec2:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:volume/*"
        ]
      },
      {
        Effect   = "Allow"
        Action   = "ec2:RunInstances"
        Resource = "arn:aws:ec2:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:instance/*"
        Condition = {
          StringEquals = {
            "aws:RequestTag/ManagedBy" = "provisioner-lambda"
          }
        }
      },
      # Terminate instances - only those managed by provisioner
      {
        Effect   = "Allow"
        Action   = "ec2:TerminateInstances"
        Resource = "*"
        Condition = {
          StringEquals = {
            "ec2:ResourceTag/ManagedBy" = "provisioner-lambda"
          }
        }
      },
      # Tagging
      {
        Effect   = "Allow"
        Action   = "ec2:CreateTags"
        Resource = "*"
        Condition = {
          StringEquals = {
            "ec2:CreateAction" = ["CreateSubnet", "RunInstances"]
          }
        }
      }
    ]
  })
}

# ------------------------------------------------------------------------------
# IAM PassRole - Allow Lambda to attach instance profile to EC2s
# ------------------------------------------------------------------------------

resource "aws_iam_role_policy" "lambda_iam" {
  name = "iam-passrole"
  role = aws_iam_role.lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "iam:PassRole"
        Resource = aws_iam_role.range_instance.arn
      }
    ]
  })
}

# ------------------------------------------------------------------------------
# S3 Access - Agent Installers
# ------------------------------------------------------------------------------

resource "aws_iam_role_policy" "lambda_s3" {
  name = "s3-agent-access"
  role = aws_iam_role.lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:ListBucket"
        ]
        Resource = [
          "arn:aws:s3:::${var.agent_s3_bucket}",
          "arn:aws:s3:::${var.agent_s3_bucket}/*"
        ]
      }
    ]
  })
}

# ------------------------------------------------------------------------------
# Secrets Manager - Kali SSH Keys
# ------------------------------------------------------------------------------

resource "aws_iam_role_policy" "lambda_secrets" {
  name = "secrets-manager-kali-ssh"
  role = aws_iam_role.lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:CreateSecret",
          "secretsmanager:DeleteSecret",
          "secretsmanager:TagResource"
        ]
        Resource = "arn:aws:secretsmanager:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:secret:shifter/${var.environment}/range/*/kali-ssh-key-*"
      }
    ]
  })
}
