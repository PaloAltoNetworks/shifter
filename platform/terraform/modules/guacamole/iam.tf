# ------------------------------------------------------------------------------
# ECS Execution Role
# ------------------------------------------------------------------------------
# Used by ECS to pull container images and write logs

resource "aws_iam_role" "ecs_execution" {
  name = "${var.name_prefix}-guacamole-ecs-execution"

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
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["ecr:GetAuthorizationToken"]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage"
        ]
        Resource = [
          var.guacd_ecr_repository_arn,
          var.guacamole_client_ecr_repository_arn
        ]
      }
    ]
  })
}

# Allow execution role to read secrets for container environment variables
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
        aws_secretsmanager_secret.db_credentials.arn,
        aws_secretsmanager_secret.json_auth.arn
      ]
    }]
  })
}

# Allow execution role to decrypt the portal Secrets Manager CMK. Without
# this, ECS resolves task-definition `secrets = [...]` using this role
# before container start; any guacamole secret encrypted with the new CMK
# (db_credentials, json_auth — see rds.tf:36, rds.tf:73 which set
# kms_key_id = var.secrets_kms_key_arn) aborts with
# `AccessDeniedException: Access to KMS is not allowed`. Same class of
# bug as issue #52; this grant closes the gap for guacamole.
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
      Resource = var.secrets_kms_key_arn
      Condition = {
        StringEquals = {
          "kms:ViaService" = "secretsmanager.${var.aws_region}.amazonaws.com"
        }
      }
    }]
  })
}

# ------------------------------------------------------------------------------
# ECS Task Role - Guacamole Client
# ------------------------------------------------------------------------------
# Used by the Guacamole client container for runtime operations

resource "aws_iam_role" "guacamole_client_task" {
  name = "${var.name_prefix}-guacamole-client-task"

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

# Guacamole client needs to read secrets for database connection
resource "aws_iam_role_policy" "guacamole_client_secrets" {
  name = "secrets-read"
  role = aws_iam_role.guacamole_client_task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "secretsmanager:GetSecretValue"
      ]
      Resource = [
        aws_secretsmanager_secret.db_credentials.arn
      ]
    }]
  })
}

# Same kms:Decrypt grant on the client task role for runtime secret
# fetches via boto3. See ecs_execution_kms above for the rationale.
resource "aws_iam_role_policy" "guacamole_client_kms" {
  name = "kms-secrets-decrypt"
  role = aws_iam_role.guacamole_client_task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "SecretsManagerKMSAccess"
      Effect = "Allow"
      Action = [
        "kms:Decrypt",
        "kms:DescribeKey"
      ]
      Resource = var.secrets_kms_key_arn
      Condition = {
        StringEquals = {
          "kms:ViaService" = "secretsmanager.${var.aws_region}.amazonaws.com"
        }
      }
    }]
  })
}

# ------------------------------------------------------------------------------
# ECS Task Role - Guacd
# ------------------------------------------------------------------------------
# Used by the guacd container - minimal permissions needed

resource "aws_iam_role" "guacd_task" {
  name = "${var.name_prefix}-guacd-task"

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
