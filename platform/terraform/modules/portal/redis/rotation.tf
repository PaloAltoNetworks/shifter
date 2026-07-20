# ------------------------------------------------------------------------------
# Redis AUTH token automatic rotation (#159)
# ------------------------------------------------------------------------------
# A custom Secrets Manager rotation Lambda rotates the ElastiCache AUTH token on
# a schedule. ElastiCache is not a native Secrets Manager rotation target, so
# the Lambda (lambda/redis_rotation.py) drives the ElastiCache `ROTATE` update
# strategy: the previous token stays valid alongside the new one, the new token
# is promoted to AWSCURRENT, and the portal ASG is refreshed so containers
# rehydrate REDIS_PASSWORD. The previous token is superseded at the next
# rotation.
#
# Gated on enable_auth_rotation (not just enable_replication): ElastiCache
# ROTATE keeps only the two newest tokens, so a consumer that never rehydrates
# loses auth at the next rotation. Automatic rotation is therefore enabled only
# where a refreshable consumer target exists — the portal ASG — which the root
# wires via enable_auth_rotation = enable_autoscaling and portal_asg_name. The
# single-instance path leaves the AUTH token to the documented manual rotation.
locals {
  rotation_enabled = var.enable_replication && var.enable_auth_rotation
  iam_name_prefix  = coalesce(var.iam_name_prefix, var.name_prefix)
}

data "archive_file" "rotation" {
  count = local.rotation_enabled ? 1 : 0

  type        = "zip"
  source_file = "${path.module}/lambda/redis_rotation.py"
  output_path = "${path.module}/lambda/redis_rotation.zip"
}

# Dedicated security group so the rotation Lambda can reach Redis (testSecret
# opens a TLS RESP AUTH check). Egress only; ingress to Redis is granted by the
# rule below on the Redis SG.
resource "aws_security_group" "rotation" {
  count = local.rotation_enabled ? 1 : 0

  name        = "${var.name_prefix}-redis-rotation-sg"
  description = "Redis AUTH rotation Lambda"
  vpc_id      = var.vpc_id

  egress {
    description = "All outbound (Secrets Manager, ElastiCache, Redis TLS)"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(var.tags, {
    Name   = "${var.name_prefix}-redis-rotation-sg"
    Module = "redis"
  })
}

resource "aws_security_group_rule" "redis_from_rotation" {
  count = local.rotation_enabled ? 1 : 0

  type                     = "ingress"
  from_port                = 6379
  to_port                  = 6379
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.rotation[0].id
  security_group_id        = aws_security_group.this.id
  description              = "Redis AUTH rotation Lambda TLS auth check"
}

resource "aws_cloudwatch_log_group" "rotation" {
  count = local.rotation_enabled ? 1 : 0

  name              = "/aws/lambda/${var.name_prefix}-redis-rotation"
  retention_in_days = 365
  # CloudWatch Logs cannot use the Secrets Manager CMK (its key policy is
  # scoped via kms:ViaService to secretsmanager only, so the logs service is
  # denied). Use the dedicated CloudWatch Logs CMK, whose key policy grants
  # the logs.<region> service principal.
  kms_key_id = var.cloudwatch_logs_kms_key_arn

  tags = merge(var.tags, {
    Name   = "${var.name_prefix}-redis-rotation-logs"
    Module = "redis"
  })
}

resource "aws_lambda_function" "rotation" {
  count = local.rotation_enabled ? 1 : 0

  # checkov:skip=CKV_AWS_50:Scheduled rotation Lambda; CloudWatch logs are sufficient observability, no X-Ray.
  # checkov:skip=CKV_AWS_115:Reserved concurrency is unnecessary; Secrets Manager invokes the rotation function serially on a schedule.
  # checkov:skip=CKV_AWS_116:DLQ does not apply; Secrets Manager owns the rotation retry/alarm lifecycle.
  # checkov:skip=CKV_AWS_173:Env vars are non-sensitive (replication-group id, Redis host/port, ASG name); the AUTH token is read from Secrets Manager, never an env var.
  # checkov:skip=CKV_AWS_272:Lambda code signing requires CodeArtifact + Signer; out of scope (ADR-004-R11 #757).
  function_name    = "${var.name_prefix}-redis-rotation"
  filename         = data.archive_file.rotation[0].output_path
  source_code_hash = data.archive_file.rotation[0].output_base64sha256
  handler          = "redis_rotation.handler"
  runtime          = "python3.12"
  timeout          = 900
  memory_size      = 128

  role = aws_iam_role.rotation[0].arn

  vpc_config {
    subnet_ids         = var.subnet_ids
    security_group_ids = [aws_security_group.rotation[0].id]
  }

  environment {
    variables = {
      REPLICATION_GROUP_ID = "${var.name_prefix}-redis"
      REDIS_HOST           = aws_elasticache_replication_group.ha[0].primary_endpoint_address
      REDIS_PORT           = "6379"
      ASG_NAME             = var.portal_asg_name
    }
  }

  tags = merge(var.tags, {
    Name   = "${var.name_prefix}-redis-rotation"
    Module = "redis"
  })

  depends_on = [aws_cloudwatch_log_group.rotation]
}

resource "aws_lambda_permission" "rotation" {
  count = local.rotation_enabled ? 1 : 0

  statement_id  = "AllowSecretsManagerInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.rotation[0].function_name
  principal     = "secretsmanager.amazonaws.com"
  source_arn    = aws_secretsmanager_secret.redis_auth[0].arn
}

resource "aws_secretsmanager_secret_rotation" "redis_auth" {
  count = local.rotation_enabled ? 1 : 0

  # checkov:skip=CKV_AWS_304:Rotation is configured here; redis_auth_rotation_days is bounded to <=90 by variable validation, so the cadence is always within the 90-day window. Checkov cannot resolve the variable default to confirm it.
  secret_id           = aws_secretsmanager_secret.redis_auth[0].id
  rotation_lambda_arn = aws_lambda_function.rotation[0].arn

  rotation_rules {
    automatically_after_days = var.redis_auth_rotation_days
  }

  depends_on = [aws_lambda_permission.rotation]
}

# ------------------------------------------------------------------------------
# Rotation Lambda IAM
# ------------------------------------------------------------------------------

resource "aws_iam_role" "rotation" {
  count = local.rotation_enabled ? 1 : 0

  name = "${local.iam_name_prefix}-redis-rotation-role"

  # The deploy role's iam:CreateRole is conditioned on this exact CI
  # permissions boundary; without it, creating this role is denied.
  permissions_boundary = var.permissions_boundary_arn != "" ? var.permissions_boundary_arn : null

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = var.tags
}

# VPC ENI management for a VPC-attached Lambda. CreateNetworkInterface etc. do
# not support resource-level scoping, hence the "*" resource (AWS-documented).
resource "aws_iam_role_policy" "rotation_vpc" {
  count = local.rotation_enabled ? 1 : 0

  name = "vpc-eni"
  role = aws_iam_role.rotation[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "ec2:CreateNetworkInterface",
        "ec2:DescribeNetworkInterfaces",
        "ec2:DeleteNetworkInterface",
      ]
      Resource = "*"
    }]
  })
}

resource "aws_iam_role_policy" "rotation_logs" {
  count = local.rotation_enabled ? 1 : 0

  name = "logs"
  role = aws_iam_role.rotation[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
      Resource = "${aws_cloudwatch_log_group.rotation[0].arn}:*"
    }]
  })
}

resource "aws_iam_role_policy" "rotation_secrets" {
  count = local.rotation_enabled ? 1 : 0

  name = "secrets"
  role = aws_iam_role.rotation[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue",
          "secretsmanager:PutSecretValue",
          "secretsmanager:UpdateSecretVersionStage",
          "secretsmanager:DescribeSecret",
        ]
        Resource = aws_secretsmanager_secret.redis_auth[0].arn
      },
      {
        Effect   = "Allow"
        Action   = ["kms:Decrypt", "kms:GenerateDataKey"]
        Resource = var.secrets_kms_key_arn
      },
    ]
  })
}

resource "aws_iam_role_policy" "rotation_elasticache" {
  count = local.rotation_enabled ? 1 : 0

  name = "elasticache"
  role = aws_iam_role.rotation[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "elasticache:ModifyReplicationGroup",
        "elasticache:DescribeReplicationGroups",
      ]
      Resource = "arn:aws:elasticache:*:*:replicationgroup:${var.name_prefix}-redis"
    }]
  })
}

# ASG instance refresh so consumers rehydrate the new token after promotion.
# rotation_enabled implies enable_auth_rotation, which the root sets only with a
# refreshable ASG, so portal_asg_name is populated here. Scoped to that ASG.
resource "aws_iam_role_policy" "rotation_asg_refresh" {
  count = local.rotation_enabled ? 1 : 0

  name = "asg-refresh"
  role = aws_iam_role.rotation[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "autoscaling:StartInstanceRefresh"
      Resource = "arn:aws:autoscaling:*:*:autoScalingGroup:*:autoScalingGroupName/${var.portal_asg_name}"
    }]
  })
}
