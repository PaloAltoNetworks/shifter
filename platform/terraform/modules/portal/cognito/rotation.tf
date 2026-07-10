# ------------------------------------------------------------------------------
# Cognito client-secret rotation (#159)
# ------------------------------------------------------------------------------
# Cognito has no in-place client-secret rotation API, so rotation is an
# operator-triggered blue/green client replacement: cognito_rotation.handler
# (invoked on demand via `aws lambda invoke`) creates a new app client copying
# the current one's config, writes it into the OIDC secret bundle, and refreshes
# the portal ASG. It is NOT scheduled; the EventBridge schedule below only
# emails the admin a reminder when rotation is due. The previous client is left
# for the operator to retire after drain (see docs/dev/secrets-rotation-runbook.md).

data "archive_file" "rotation" {
  type        = "zip"
  source_file = "${path.module}/lambda/cognito_rotation.py"
  output_path = "${path.module}/lambda/cognito_rotation.zip"
}

resource "aws_cloudwatch_log_group" "rotation" {
  name              = "/aws/lambda/${var.name_prefix}-cognito-rotation"
  retention_in_days = 365
  kms_key_id        = aws_kms_key.cloudwatch_logs.arn

  tags = merge(var.tags, { Name = "${var.name_prefix}-cognito-rotation-logs" })
}

resource "aws_lambda_function" "rotation" {
  # checkov:skip=CKV_AWS_50:Operator-invoked rotation Lambda; CloudWatch logs are sufficient observability, no X-Ray.
  # checkov:skip=CKV_AWS_115:Reserved concurrency unnecessary; invoked on demand by an operator.
  # checkov:skip=CKV_AWS_116:DLQ does not apply to a synchronous operator-invoked function.
  # checkov:skip=CKV_AWS_117:Calls only public AWS APIs (Cognito, Secrets Manager, Auto Scaling); a VPC config needs interface endpoints for no security gain.
  # checkov:skip=CKV_AWS_173:Env vars are non-sensitive (secret ARN reference, ASG name); the client secret is read from Secrets Manager, never an env var.
  # checkov:skip=CKV_AWS_272:Lambda code signing requires CodeArtifact + Signer; out of scope (ADR-004-R11 #757).
  function_name    = "${var.name_prefix}-cognito-rotation"
  filename         = data.archive_file.rotation.output_path
  source_code_hash = data.archive_file.rotation.output_base64sha256
  handler          = "cognito_rotation.handler"
  runtime          = "python3.12"
  timeout          = 120
  memory_size      = 128

  role = aws_iam_role.rotation.arn

  environment {
    variables = {
      COGNITO_SECRET_ID = aws_secretsmanager_secret.cognito_client.arn
      ASG_NAME          = var.portal_asg_name
    }
  }

  tags = merge(var.tags, { Name = "${var.name_prefix}-cognito-rotation" })

  depends_on = [aws_cloudwatch_log_group.rotation]
}

# ------------------------------------------------------------------------------
# Rotation Lambda IAM
# ------------------------------------------------------------------------------

resource "aws_iam_role" "rotation" {
  name                 = "${local.iam_name_prefix}-cognito-rotation-role"
  permissions_boundary = var.permissions_boundary_arn

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

resource "aws_iam_role_policy" "rotation_logs" {
  name = "logs"
  role = aws_iam_role.rotation.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
      Resource = "${aws_cloudwatch_log_group.rotation.arn}:*"
    }]
  })
}

resource "aws_iam_role_policy" "rotation_secrets" {
  name = "secrets"
  role = aws_iam_role.rotation.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue", "secretsmanager:PutSecretValue", "secretsmanager:DescribeSecret"]
        Resource = aws_secretsmanager_secret.cognito_client.arn
      },
      {
        Effect   = "Allow"
        Action   = ["kms:Decrypt", "kms:GenerateDataKey"]
        Resource = var.secrets_kms_key_arn
      },
    ]
  })
}

resource "aws_iam_role_policy" "rotation_cognito" {
  name = "cognito"
  role = aws_iam_role.rotation.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "cognito-idp:DescribeUserPoolClient",
        "cognito-idp:CreateUserPoolClient",
      ]
      Resource = aws_cognito_user_pool.main.arn
    }]
  })
}

# ASG instance refresh so consumers rehydrate the new client. Created only on
# the autoscaling path (static gate); scoped to the portal ASG.
resource "aws_iam_role_policy" "rotation_asg_refresh" {
  count = var.enable_autoscaling ? 1 : 0

  name = "asg-refresh"
  role = aws_iam_role.rotation.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "autoscaling:StartInstanceRefresh"
      Resource = "arn:aws:autoscaling:*:*:autoScalingGroup:*:autoScalingGroupName/${var.portal_asg_name}"
    }]
  })
}

# ------------------------------------------------------------------------------
# Scheduled rotation reminder (EventBridge Scheduler -> SNS email)
# ------------------------------------------------------------------------------
# Emails the admin on a cadence that Cognito client-secret rotation is due. It
# does NOT rotate anything; an operator runs the Lambda above per the runbook.

resource "aws_scheduler_schedule" "rotation_reminder" {
  count = var.enable_rotation_reminder ? 1 : 0

  # checkov:skip=CKV_AWS_297:The schedule input is a non-sensitive reminder message (no secret data); a CMK adds no protection and the portal Secrets CMK is kms:ViaService-scoped to Secrets Manager.
  name = "${var.name_prefix}-cognito-rotation-reminder"

  flexible_time_window {
    mode = "OFF"
  }

  schedule_expression          = "rate(${var.cognito_rotation_reminder_days} days)"
  schedule_expression_timezone = "UTC"

  target {
    arn      = var.alerts_topic_arn
    role_arn = aws_iam_role.reminder[0].arn

    input = jsonencode({
      default = "Reminder: the Cognito portal client secret is due for rotation. Run the operator rotation procedure in docs/dev/secrets-rotation-runbook.md (Cognito client secret)."
    })
  }
}

resource "aws_iam_role" "reminder" {
  count = var.enable_rotation_reminder ? 1 : 0

  name                 = "${local.iam_name_prefix}-cognito-reminder-role"
  permissions_boundary = var.permissions_boundary_arn

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "scheduler.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = var.tags
}

resource "aws_iam_role_policy" "reminder_publish" {
  count = var.enable_rotation_reminder ? 1 : 0

  name = "sns-publish"
  role = aws_iam_role.reminder[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "sns:Publish"
      Resource = var.alerts_topic_arn
    }]
  })
}
