# Step Functions State Machines for Range Provisioning
#
# Creates two state machines:
# 1. Provision Range - Creates all resources with error handling
# 2. Teardown Range - Destroys all resources

# ------------------------------------------------------------------------------
# IAM Role for Step Functions
# ------------------------------------------------------------------------------

resource "aws_iam_role" "step_functions" {
  name = "${var.name_prefix}-provisioner-sfn"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "states.amazonaws.com"
        }
      }
    ]
  })

  tags = merge(var.tags, {
    Name   = "${var.name_prefix}-provisioner-sfn"
    Module = "provisioner"
  })
}

resource "aws_iam_role_policy" "step_functions_lambda" {
  name = "invoke-lambdas"
  role = aws_iam_role.step_functions.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = "lambda:InvokeFunction"
        Resource = [
          aws_lambda_function.create_subnet.arn,
          aws_lambda_function.create_victim.arn,
          aws_lambda_function.create_kali.arn,
          aws_lambda_function.verify_agent.arn,
          aws_lambda_function.mark_ready.arn,
          aws_lambda_function.cleanup.arn,
          aws_lambda_function.find_stale_ranges.arn,
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy" "step_functions_logs" {
  name = "cloudwatch-logs"
  role = aws_iam_role.step_functions.id

  # Note: Resource = "*" is required by AWS for Step Functions logging.
  # These are account-level log delivery management permissions, not log write permissions.
  # The actual log group is scoped in logging_configuration.
  # See: https://docs.aws.amazon.com/step-functions/latest/dg/cw-logs.html
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogDelivery",
          "logs:GetLogDelivery",
          "logs:UpdateLogDelivery",
          "logs:DeleteLogDelivery",
          "logs:ListLogDeliveries",
          "logs:PutResourcePolicy",
          "logs:DescribeResourcePolicies",
          "logs:DescribeLogGroups"
        ]
        Resource = "*"
      }
    ]
  })
}

# ------------------------------------------------------------------------------
# CloudWatch Log Group for Step Functions
# ------------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "step_functions" {
  name              = "/aws/stepfunctions/${var.name_prefix}-provisioner"
  retention_in_days = 30

  tags = merge(var.tags, {
    Name   = "${var.name_prefix}-provisioner-sfn-logs"
    Module = "provisioner"
  })
}

# ------------------------------------------------------------------------------
# Provision Range State Machine
# ------------------------------------------------------------------------------

resource "aws_sfn_state_machine" "provision_range" {
  name     = "${var.name_prefix}-provision-range"
  role_arn = aws_iam_role.step_functions.arn

  definition = templatefile("${path.module}/state_machines/provision_range.asl.json", {
    create_subnet_lambda_arn     = aws_lambda_function.create_subnet.arn
    create_victim_lambda_arn     = aws_lambda_function.create_victim.arn
    create_kali_lambda_arn       = aws_lambda_function.create_kali.arn
    verify_agent_lambda_arn      = aws_lambda_function.verify_agent.arn
    mark_ready_lambda_arn        = aws_lambda_function.mark_ready.arn
    cleanup_lambda_arn           = aws_lambda_function.cleanup.arn
    find_stale_ranges_lambda_arn = aws_lambda_function.find_stale_ranges.arn
  })

  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.step_functions.arn}:*"
    include_execution_data = true
    level                  = "ERROR"
  }

  tags = merge(var.tags, {
    Name   = "${var.name_prefix}-provision-range"
    Module = "provisioner"
  })
}

# ------------------------------------------------------------------------------
# Teardown Range State Machine
# ------------------------------------------------------------------------------

resource "aws_sfn_state_machine" "teardown_range" {
  name     = "${var.name_prefix}-teardown-range"
  role_arn = aws_iam_role.step_functions.arn

  definition = templatefile("${path.module}/state_machines/teardown_range.asl.json", {
    cleanup_lambda_arn = aws_lambda_function.cleanup.arn
  })

  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.step_functions.arn}:*"
    include_execution_data = true
    level                  = "ERROR"
  }

  tags = merge(var.tags, {
    Name   = "${var.name_prefix}-teardown-range"
    Module = "provisioner"
  })
}

# ------------------------------------------------------------------------------
# Cleanup Stale Ranges State Machine
# ------------------------------------------------------------------------------

resource "aws_sfn_state_machine" "cleanup_stale_ranges" {
  name     = "${var.name_prefix}-cleanup-stale-ranges"
  role_arn = aws_iam_role.step_functions.arn

  definition = templatefile("${path.module}/state_machines/cleanup_stale_ranges.asl.json", {
    find_stale_ranges_lambda_arn = aws_lambda_function.find_stale_ranges.arn
    cleanup_lambda_arn           = aws_lambda_function.cleanup.arn
  })

  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.step_functions.arn}:*"
    include_execution_data = true
    level                  = "ERROR"
  }

  tags = merge(var.tags, {
    Name   = "${var.name_prefix}-cleanup-stale-ranges"
    Module = "provisioner"
  })
}

# ------------------------------------------------------------------------------
# EventBridge Rule to Trigger Stale Cleanup
# ------------------------------------------------------------------------------

resource "aws_cloudwatch_event_rule" "stale_cleanup" {
  name                = "${var.name_prefix}-stale-range-cleanup"
  description         = "Trigger stale range cleanup every 15 minutes"
  schedule_expression = "rate(15 minutes)"

  tags = merge(var.tags, {
    Name   = "${var.name_prefix}-stale-range-cleanup"
    Module = "provisioner"
  })
}

resource "aws_cloudwatch_event_target" "stale_cleanup" {
  rule      = aws_cloudwatch_event_rule.stale_cleanup.name
  target_id = "cleanup-stale-ranges"
  arn       = aws_sfn_state_machine.cleanup_stale_ranges.arn
  role_arn  = aws_iam_role.eventbridge.arn
}

# IAM Role for EventBridge to invoke Step Functions
resource "aws_iam_role" "eventbridge" {
  name = "${var.name_prefix}-provisioner-eventbridge"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "events.amazonaws.com"
        }
      }
    ]
  })

  tags = merge(var.tags, {
    Name   = "${var.name_prefix}-provisioner-eventbridge"
    Module = "provisioner"
  })
}

resource "aws_iam_role_policy" "eventbridge_sfn" {
  name = "invoke-step-functions"
  role = aws_iam_role.eventbridge.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "states:StartExecution"
        Resource = aws_sfn_state_machine.cleanup_stale_ranges.arn
      }
    ]
  })
}
