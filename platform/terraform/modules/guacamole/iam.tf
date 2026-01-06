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
        aws_secretsmanager_secret.db_credentials.arn
      ]
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
