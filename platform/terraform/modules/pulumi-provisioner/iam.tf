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
        # Permissions based on Terraform AWS provider ec2_instance.go:
        # - RunInstances, DescribeInstances, TerminateInstances for lifecycle
        # - CreateTags for tagging (tags are applied during RunInstances)
        # - DescribeImages for AMI validation
        Sid    = "EC2InstanceOperations"
        Effect = "Allow"
        Action = [
          "ec2:RunInstances",
          "ec2:TerminateInstances",
          "ec2:CreateTags",
          "ec2:Describe*"
        ]
        Resource = "*"
      },
      {
        # Permissions based on Terraform AWS provider vpc_subnet.go:
        # - CreateSubnet, DescribeSubnets, DeleteSubnet for lifecycle
        # Note: CreateTags is in EC2InstanceOperations and applies to all EC2 resources
        Sid    = "EC2SubnetOperations"
        Effect = "Allow"
        Action = [
          "ec2:CreateSubnet",
          "ec2:DescribeSubnets",
          "ec2:DeleteSubnet"
        ]
        Resource = "*"
      },
      {
        # Permissions based on Terraform AWS provider vpc_route_table_association.go:
        # - AssociateRouteTable, DisassociateRouteTable for lifecycle
        # - DescribeRouteTables for reading association state
        Sid    = "EC2RouteTableOperations"
        Effect = "Allow"
        Action = [
          "ec2:AssociateRouteTable",
          "ec2:DisassociateRouteTable",
          "ec2:DescribeRouteTables"
        ]
        Resource = "*"
      },
      {
        # Read-only permissions for validating references (VPC, AZ, SG)
        Sid    = "EC2ReadOnlyValidation"
        Effect = "Allow"
        Action = [
          "ec2:DescribeVpcs",
          "ec2:DescribeAvailabilityZones",
          "ec2:DescribeSecurityGroups"
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

  # Permissions based on Terraform AWS provider source code analysis:
  # - secret.go: CreateSecret, DescribeSecret, GetResourcePolicy, DeleteSecret
  # - secret_version.go: PutSecretValue, GetSecretValue, ListSecretVersionIds, UpdateSecretVersionStage
  # Ref: github.com/hashicorp/terraform-provider-aws/internal/service/secretsmanager/
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        # secret.go - resourceSecretCreate, resourceSecretRead, resourceSecretDelete
        "secretsmanager:CreateSecret",
        "secretsmanager:TagResource",
        "secretsmanager:DescribeSecret",
        "secretsmanager:GetResourcePolicy",
        "secretsmanager:DeleteSecret",
        # secret_version.go - resourceSecretVersionCreate, resourceSecretVersionRead, resourceSecretVersionDelete
        "secretsmanager:PutSecretValue",
        "secretsmanager:GetSecretValue",
        "secretsmanager:ListSecretVersionIds",
        "secretsmanager:UpdateSecretVersionStage"
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
# Task Role Policy - SSM Parameters (DC Config)
# ------------------------------------------------------------------------------
# DC component creates SSM parameters to store domain config (credentials, etc.)
# that domain members retrieve during setup.

resource "aws_iam_role_policy" "ssm_parameters" {
  name = "ssm-parameters"
  role = aws_iam_role.ecs_task.id

  # Permissions based on AWS docs for SSM Parameter Store:
  # https://docs.aws.amazon.com/systems-manager/latest/userguide/sysman-paramstore-access.html
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "SSMParameterOperations"
        Effect = "Allow"
        Action = [
          # Create/Update
          "ssm:PutParameter",
          # Read
          "ssm:GetParameter",
          "ssm:GetParameters",
          "ssm:GetParameterHistory",
          # Delete
          "ssm:DeleteParameter",
          # Tagging
          "ssm:AddTagsToResource",
          "ssm:ListTagsForResource",
          "ssm:RemoveTagsFromResource"
        ]
        Resource = "arn:aws:ssm:${local.region}:${local.account_id}:parameter/shifter/${var.environment}/range/*"
      },
      {
        # DescribeParameters required by Pulumi/Terraform for metadata lookup
        # Must be * resource per AWS API requirements
        Sid      = "SSMDescribeParameters"
        Effect   = "Allow"
        Action   = "ssm:DescribeParameters"
        Resource = "*"
      },
      {
        # KMS permissions for SecureString parameters
        # Uses AWS managed key for SSM via service condition
        Sid    = "KMSForSecureStringParameters"
        Effect = "Allow"
        Action = [
          "kms:Encrypt",
          "kms:Decrypt",
          "kms:GenerateDataKey"
        ]
        Resource = "*"
        Condition = {
          StringEquals = {
            "kms:ViaService" = "ssm.${local.region}.amazonaws.com"
          }
        }
      }
    ]
  })
}

# ------------------------------------------------------------------------------
# Task Role Policy - SSM Run Command (for DC setup orchestration)
# ------------------------------------------------------------------------------
# Pulumi uses SSM Run Command to orchestrate DC setup:
# - Install AD DS feature
# - Reboot and wait for instance
# - Promote to Domain Controller
# - Verify AD DS is running

resource "aws_iam_role_policy" "ssm_run_command" {
  name = "ssm-run-command"
  role = aws_iam_role.ecs_task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "SSMSendCommand"
        Effect = "Allow"
        Action = [
          "ssm:SendCommand"
        ]
        Resource = [
          "arn:aws:ec2:${local.region}:${local.account_id}:instance/*",
          "arn:aws:ssm:${local.region}::document/AWS-RunPowerShellScript",
          "arn:aws:ssm:${local.region}::document/AWS-RunShellScript"
        ]
      },
      {
        Sid    = "SSMGetCommandInvocation"
        Effect = "Allow"
        Action = [
          "ssm:GetCommandInvocation",
          "ssm:ListCommandInvocations"
        ]
        Resource = "*"
      },
      {
        Sid    = "SSMDescribeInstances"
        Effect = "Allow"
        Action = [
          "ssm:DescribeInstanceInformation"
        ]
        Resource = "*"
      },
      {
        Sid    = "EC2RebootInstances"
        Effect = "Allow"
        Action = [
          "ec2:RebootInstances"
        ]
        Resource = "arn:aws:ec2:${local.region}:${local.account_id}:instance/*"
      }
    ]
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
        # Dedicated CMK for Pulumi stack secrets encryption
        Resource = var.pulumi_secrets_kms_key_arn
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

# ------------------------------------------------------------------------------
# Task Role Policy - SNS (for range event publishing)
# ------------------------------------------------------------------------------
# Provisioner publishes range lifecycle events to SNS for fan-out to
# Django services (CMS, Engine, Mission Control).

resource "aws_iam_role_policy" "sns_publish" {
  name = "sns-publish"
  role = aws_iam_role.ecs_task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "SNSPublishRangeEvents"
      Effect = "Allow"
      Action = [
        "sns:Publish"
      ]
      Resource = var.sns_topic_arn
    }]
  })
}
