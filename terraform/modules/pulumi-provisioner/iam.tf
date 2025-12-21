# ------------------------------------------------------------------------------
# ECS Execution Role
# ------------------------------------------------------------------------------
# Used by ECS to pull container images and write logs

resource "aws_iam_role" "ecs_execution" {
  name = "${var.name_prefix}-pulumi-ecs-execution"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "ecs-tasks.amazonaws.com"
      }
    }]
  })

  tags = local.common_tags
}

resource "aws_iam_role_policy_attachment" "ecs_execution" {
  role       = aws_iam_role.ecs_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "ecs_execution_ecr" {
  name = "ecr-pull"
  role = aws_iam_role.ecs_execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "ecr:GetAuthorizationToken",
        "ecr:BatchCheckLayerAvailability",
        "ecr:GetDownloadUrlForLayer",
        "ecr:BatchGetImage"
      ]
      Resource = "*"
    }]
  })
}

# ------------------------------------------------------------------------------
# ECS Task Role
# ------------------------------------------------------------------------------
# Used by the Pulumi provisioner container for AWS operations

resource "aws_iam_role" "ecs_task" {
  name = "${var.name_prefix}-pulumi-ecs-task"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "ecs-tasks.amazonaws.com"
      }
    }]
  })

  tags = local.common_tags
}

# ------------------------------------------------------------------------------
# Task Role Policy - Pulumi State
# ------------------------------------------------------------------------------

resource "aws_iam_role_policy" "pulumi_state" {
  name = "pulumi-state"
  role = aws_iam_role.ecs_task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
          "s3:ListBucket"
        ]
        Resource = [
          var.pulumi_state_bucket_arn,
          "${var.pulumi_state_bucket_arn}/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:DeleteItem"
        ]
        Resource = var.pulumi_locks_table_arn
      }
    ]
  })
}

# ------------------------------------------------------------------------------
# Task Role Policy - EC2 Provisioning
# ------------------------------------------------------------------------------

resource "aws_iam_role_policy" "ec2_provisioning" {
  name = "ec2-provisioning"
  role = aws_iam_role.ecs_task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "EC2InstanceOperations"
        Effect = "Allow"
        Action = [
          "ec2:RunInstances",
          "ec2:TerminateInstances",
          "ec2:DescribeInstances",
          "ec2:DescribeInstanceStatus",
          "ec2:CreateTags",
          "ec2:DescribeTags",
          "ec2:DescribeImages",
          "ec2:DescribeKeyPairs",
          "ec2:CreateKeyPair",
          "ec2:DeleteKeyPair"
        ]
        Resource = "*"
      },
      {
        Sid    = "EC2SubnetOperations"
        Effect = "Allow"
        Action = [
          "ec2:CreateSubnet",
          "ec2:DeleteSubnet",
          "ec2:DescribeSubnets",
          "ec2:ModifySubnetAttribute"
        ]
        Resource = "*"
      },
      {
        Sid    = "EC2SecurityGroupOperations"
        Effect = "Allow"
        Action = [
          "ec2:CreateSecurityGroup",
          "ec2:DeleteSecurityGroup",
          "ec2:AuthorizeSecurityGroupIngress",
          "ec2:AuthorizeSecurityGroupEgress",
          "ec2:RevokeSecurityGroupIngress",
          "ec2:RevokeSecurityGroupEgress",
          "ec2:DescribeSecurityGroups"
        ]
        Resource = "*"
      },
      {
        Sid    = "EC2RouteTableOperations"
        Effect = "Allow"
        Action = [
          "ec2:CreateRouteTableAssociation",
          "ec2:DeleteRouteTableAssociation",
          "ec2:DescribeRouteTables"
        ]
        Resource = "*"
      },
      {
        Sid    = "EC2NetworkOperations"
        Effect = "Allow"
        Action = [
          "ec2:DescribeVpcs",
          "ec2:DescribeAvailabilityZones"
        ]
        Resource = "*"
      },
      {
        Sid      = "PassRoleToInstances"
        Effect   = "Allow"
        Action   = "iam:PassRole"
        Resource = var.range_instance_role_arn
      }
    ]
  })
}

# ------------------------------------------------------------------------------
# Task Role Policy - Secrets Manager
# ------------------------------------------------------------------------------

resource "aws_iam_role_policy" "secrets_manager" {
  name = "secrets-manager"
  role = aws_iam_role.ecs_task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "secretsmanager:CreateSecret",
        "secretsmanager:DeleteSecret",
        "secretsmanager:PutSecretValue",
        "secretsmanager:GetSecretValue",
        "secretsmanager:TagResource"
      ]
      Resource = "arn:aws:secretsmanager:${local.region}:${local.account_id}:secret:shifter/${var.environment}/range/*"
    }]
  })
}

# ------------------------------------------------------------------------------
# Task Role Policy - RDS IAM Authentication
# ------------------------------------------------------------------------------

resource "aws_iam_role_policy" "rds_iam_auth" {
  name = "rds-iam-auth"
  role = aws_iam_role.ecs_task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "rds-db:connect"
      Resource = "arn:aws:rds-db:${local.region}:${local.account_id}:dbuser:${var.db_resource_id}/provisioner_lambda"
    }]
  })
}

# ------------------------------------------------------------------------------
# Task Role Policy - S3 Agent Bucket
# ------------------------------------------------------------------------------

resource "aws_iam_role_policy" "s3_agent" {
  name = "s3-agent-read"
  role = aws_iam_role.ecs_task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "s3:GetObject",
        "s3:ListBucket"
      ]
      Resource = [
        var.agent_s3_bucket_arn,
        "${var.agent_s3_bucket_arn}/*"
      ]
    }]
  })
}

# ------------------------------------------------------------------------------
# Task Role Policy - KMS (for Pulumi secrets encryption)
# ------------------------------------------------------------------------------
# Pulumi's awskms:// secrets provider calls KMS directly (not via Secrets Manager),
# so we need separate statements for each use case.

resource "aws_iam_role_policy" "kms" {
  name = "kms-access"
  role = aws_iam_role.ecs_task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "PulumiSecretsEncryption"
        Effect = "Allow"
        Action = [
          "kms:Encrypt",
          "kms:Decrypt",
          "kms:GenerateDataKey",
          "kms:DescribeKey"
        ]
        # Pulumi uses the aws/secretsmanager key directly for stack secrets
        # Policy checks are done against the key ARN, not the alias ARN
        Resource = data.aws_kms_key.secretsmanager.arn
      },
      {
        Sid    = "SecretsManagerKMSAccess"
        Effect = "Allow"
        Action = [
          "kms:Encrypt",
          "kms:Decrypt",
          "kms:GenerateDataKey"
        ]
        Resource = "*"
        Condition = {
          StringEquals = {
            "kms:ViaService" = "secretsmanager.${local.region}.amazonaws.com"
          }
        }
      }
    ]
  })
}
