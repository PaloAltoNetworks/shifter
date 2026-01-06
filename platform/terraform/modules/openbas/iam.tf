# OpenBAS IAM Roles
#
# Creates:
# - ECS Task Execution Role (for pulling images, accessing secrets)
# - ECS Task Role (for application-level permissions)

# ------------------------------------------------------------------------------
# ECS Task Execution Role
# ------------------------------------------------------------------------------
# Used by ECS agent to pull container images and access secrets

resource "aws_iam_role" "ecs_execution" {
  name = "${var.name_prefix}-openbas-execution"

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

# Allow access to Secrets Manager secrets
resource "aws_iam_role_policy" "ecs_execution_secrets" {
  name = "${var.name_prefix}-openbas-execution-secrets"
  role = aws_iam_role.ecs_execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue"
        ]
        Resource = [
          aws_secretsmanager_secret.db_credentials.arn,
          aws_secretsmanager_secret.admin_token.arn,
        ]
      }
    ]
  })
}

# ------------------------------------------------------------------------------
# ECS Task Role
# ------------------------------------------------------------------------------
# Used by the running container for application permissions

resource "aws_iam_role" "ecs_task" {
  name = "${var.name_prefix}-openbas-task"

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

# S3 access for OpenBAS storage bucket
resource "aws_iam_role_policy" "ecs_task_s3" {
  name = "${var.name_prefix}-openbas-task-s3"
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
          aws_s3_bucket.openbas.arn,
          "${aws_s3_bucket.openbas.arn}/*"
        ]
      }
    ]
  })
}

# CloudWatch Logs access for metrics
resource "aws_iam_role_policy" "ecs_task_cloudwatch" {
  name = "${var.name_prefix}-openbas-task-cloudwatch"
  role = aws_iam_role.ecs_task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = [
          "${aws_cloudwatch_log_group.openbas.arn}:*"
        ]
      }
    ]
  })
}
