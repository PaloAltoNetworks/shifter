# ------------------------------------------------------------------------------
# ECS Execution Role
# ------------------------------------------------------------------------------
# Used by ECS to pull container images and write logs

resource "aws_iam_role" "ecs_execution" {
  name                 = "${local.iam_name_prefix}-pulumi-ecs-execution"
  permissions_boundary = var.permissions_boundary_arn

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

# Allow the ECS execution role to fetch the DC domain password secret so
# ECS can hydrate the DC_DOMAIN_PASSWORD container env var via the
# `secrets = [...]` block in task_definition.tf.
resource "aws_iam_role_policy" "ecs_execution_secrets" {
  name = "secrets-read"
  role = aws_iam_role.ecs_execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "secretsmanager:GetSecretValue"
      ]
      Resource = [
        aws_secretsmanager_secret.dc_domain_password.arn
      ]
    }]
  })
}

# Allow the ECS execution role to decrypt secrets encrypted with the portal
# Secrets Manager CMK. ECS resolves task-definition `secrets = [...]` before
# container start using the execution role, so a missing kms:Decrypt grant on
# the CMK aborts the task with `ResourceInitializationError: Access to KMS is
# not allowed` and the container never runs. Mirrors `SecretsManagerKMSAccess`
# on the task role below, but pinned to the concrete CMK ARN (preflight
# guidance: prefer the concrete CMK ARN when the role only needs the portal
# CMK). See issue #52.
resource "aws_iam_role_policy" "ecs_execution_kms" {
  name = "kms-secrets-decrypt"
  role = aws_iam_role.ecs_execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "SecretsManagerKMSAccess"
      Effect = "Allow"
      Action = [
        "kms:Decrypt",
        "kms:DescribeKey"
      ]
      Resource = var.secrets_manager_kms_key_arn
      Condition = {
        StringEquals = {
          "kms:ViaService" = "secretsmanager.${local.region}.amazonaws.com"
        }
      }
    }]
  })
}

# ------------------------------------------------------------------------------
# ECS Task Role
# ------------------------------------------------------------------------------
# Used by the engine provisioner container for AWS operations. The privileged
# provisioning permission set is substrate-neutral (#1826): it is defined once in
# modules/provisioner-iam and attached here to the ECS task role, and to the EKS
# provisioner IRSA role by modules/portal/eks. This role only owns the ECS trust
# relationship; the permissions live in the shared module.

resource "aws_iam_role" "ecs_task" {
  name                 = "${local.iam_name_prefix}-pulumi-ecs-task"
  permissions_boundary = var.permissions_boundary_arn

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
# Task Role Policy - substrate-neutral provisioner permission set
# ------------------------------------------------------------------------------
# Single source of truth shared with the EKS provisioner IRSA role (#1826).
# Moved blocks in moved.tf relocate the previously-inline/managed policies into
# this module so the live ECS role's permissions are preserved without a
# destroy/recreate.

module "provisioner_iam" {
  source = "../provisioner-iam"

  name_prefix              = var.name_prefix
  environment              = var.environment
  role_name                = aws_iam_role.ecs_task.name
  role_id                  = aws_iam_role.ecs_task.id
  permissions_boundary_arn = var.permissions_boundary_arn

  engine_state_bucket_arn     = var.engine_state_bucket_arn
  engine_locks_table_arn      = var.engine_locks_table_arn
  engine_secrets_kms_key_arn  = var.engine_secrets_kms_key_arn
  secrets_manager_kms_key_arn = var.secrets_manager_kms_key_arn
  db_resource_id              = var.db_resource_id
  agent_s3_bucket_arn         = var.agent_s3_bucket_arn
  range_vpc_id                = var.range_vpc_id
  range_availability_zone     = var.range_availability_zone
  range_instance_role_arn     = var.range_instance_role_arn
  ngfw_instance_role_arn      = var.ngfw_instance_role_arn
  tags                        = local.common_tags
}
