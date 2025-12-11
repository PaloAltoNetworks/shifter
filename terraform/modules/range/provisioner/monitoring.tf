# CloudWatch Alarms for Provisioner Monitoring
#
# Creates alarms for:
# - Step Functions execution failures
# - Step Functions execution timeouts
# - Lambda function errors

# ------------------------------------------------------------------------------
# SNS Topic for Alerts
# ------------------------------------------------------------------------------

resource "aws_sns_topic" "alerts" {
  count = var.enable_alarms ? 1 : 0

  name = "${var.name_prefix}-provisioner-alerts"

  tags = merge(var.tags, {
    Name   = "${var.name_prefix}-provisioner-alerts"
    Module = "provisioner"
  })
}

resource "aws_sns_topic_subscription" "email" {
  count = var.enable_alarms && var.alarm_email != "" ? 1 : 0

  topic_arn = aws_sns_topic.alerts[0].arn
  protocol  = "email"
  endpoint  = var.alarm_email
}

# ------------------------------------------------------------------------------
# Step Functions Alarms - Provision Range
# ------------------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "provision_failed" {
  count = var.enable_alarms ? 1 : 0

  alarm_name          = "${var.name_prefix}-provision-range-failed"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ExecutionsFailed"
  namespace           = "AWS/States"
  period              = 300
  statistic           = "Sum"
  threshold           = 0
  alarm_description   = "Provisioning state machine execution failed"
  treat_missing_data  = "notBreaching"

  dimensions = {
    StateMachineArn = aws_sfn_state_machine.provision_range.arn
  }

  alarm_actions = [aws_sns_topic.alerts[0].arn]
  ok_actions    = [aws_sns_topic.alerts[0].arn]

  tags = merge(var.tags, {
    Name   = "${var.name_prefix}-provision-range-failed"
    Module = "provisioner"
  })
}

resource "aws_cloudwatch_metric_alarm" "provision_timeout" {
  count = var.enable_alarms ? 1 : 0

  alarm_name          = "${var.name_prefix}-provision-range-timeout"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ExecutionsTimedOut"
  namespace           = "AWS/States"
  period              = 300
  statistic           = "Sum"
  threshold           = 0
  alarm_description   = "Provisioning state machine execution timed out"
  treat_missing_data  = "notBreaching"

  dimensions = {
    StateMachineArn = aws_sfn_state_machine.provision_range.arn
  }

  alarm_actions = [aws_sns_topic.alerts[0].arn]
  ok_actions    = [aws_sns_topic.alerts[0].arn]

  tags = merge(var.tags, {
    Name   = "${var.name_prefix}-provision-range-timeout"
    Module = "provisioner"
  })
}

# ------------------------------------------------------------------------------
# Step Functions Alarms - Teardown Range
# ------------------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "teardown_failed" {
  count = var.enable_alarms ? 1 : 0

  alarm_name          = "${var.name_prefix}-teardown-range-failed"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ExecutionsFailed"
  namespace           = "AWS/States"
  period              = 300
  statistic           = "Sum"
  threshold           = 0
  alarm_description   = "Teardown state machine execution failed"
  treat_missing_data  = "notBreaching"

  dimensions = {
    StateMachineArn = aws_sfn_state_machine.teardown_range.arn
  }

  alarm_actions = [aws_sns_topic.alerts[0].arn]
  ok_actions    = [aws_sns_topic.alerts[0].arn]

  tags = merge(var.tags, {
    Name   = "${var.name_prefix}-teardown-range-failed"
    Module = "provisioner"
  })
}

resource "aws_cloudwatch_metric_alarm" "teardown_timeout" {
  count = var.enable_alarms ? 1 : 0

  alarm_name          = "${var.name_prefix}-teardown-range-timeout"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ExecutionsTimedOut"
  namespace           = "AWS/States"
  period              = 300
  statistic           = "Sum"
  threshold           = 0
  alarm_description   = "Teardown state machine execution timed out"
  treat_missing_data  = "notBreaching"

  dimensions = {
    StateMachineArn = aws_sfn_state_machine.teardown_range.arn
  }

  alarm_actions = [aws_sns_topic.alerts[0].arn]
  ok_actions    = [aws_sns_topic.alerts[0].arn]

  tags = merge(var.tags, {
    Name   = "${var.name_prefix}-teardown-range-timeout"
    Module = "provisioner"
  })
}

# ------------------------------------------------------------------------------
# Step Functions Alarms - Stale Range Cleanup
# ------------------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "stale_cleanup_failed" {
  count = var.enable_alarms ? 1 : 0

  alarm_name          = "${var.name_prefix}-stale-cleanup-failed"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ExecutionsFailed"
  namespace           = "AWS/States"
  period              = 300
  statistic           = "Sum"
  threshold           = 0
  alarm_description   = "Stale range cleanup state machine execution failed"
  treat_missing_data  = "notBreaching"

  dimensions = {
    StateMachineArn = aws_sfn_state_machine.cleanup_stale_ranges.arn
  }

  alarm_actions = [aws_sns_topic.alerts[0].arn]
  ok_actions    = [aws_sns_topic.alerts[0].arn]

  tags = merge(var.tags, {
    Name   = "${var.name_prefix}-stale-cleanup-failed"
    Module = "provisioner"
  })
}

# ------------------------------------------------------------------------------
# Lambda Error Alarms
# ------------------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  for_each = var.enable_alarms ? toset([
    aws_lambda_function.create_subnet.function_name,
    aws_lambda_function.create_victim.function_name,
    aws_lambda_function.create_kali.function_name,
    aws_lambda_function.configure_librechat.function_name,
    aws_lambda_function.cleanup.function_name,
    aws_lambda_function.find_stale_ranges.function_name,
  ]) : toset([])

  alarm_name          = "${each.value}-errors"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 300
  statistic           = "Sum"
  threshold           = 0
  alarm_description   = "Lambda function ${each.value} encountered errors"
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = each.value
  }

  alarm_actions = [aws_sns_topic.alerts[0].arn]
  ok_actions    = [aws_sns_topic.alerts[0].arn]

  tags = merge(var.tags, {
    Name   = "${each.value}-errors"
    Module = "provisioner"
  })
}

# ------------------------------------------------------------------------------
# Lambda Duration Alarms (approaching timeout)
# ------------------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "lambda_duration" {
  for_each = var.enable_alarms ? toset([
    aws_lambda_function.create_subnet.function_name,
    aws_lambda_function.create_victim.function_name,
    aws_lambda_function.create_kali.function_name,
    aws_lambda_function.configure_librechat.function_name,
    aws_lambda_function.cleanup.function_name,
    aws_lambda_function.find_stale_ranges.function_name,
  ]) : toset([])

  alarm_name          = "${each.value}-duration"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "Duration"
  namespace           = "AWS/Lambda"
  period              = 300
  statistic           = "Maximum"
  # Alert if any invocation takes > 80% of timeout (240s of 300s)
  threshold          = var.lambda_timeout * 1000 * 0.8
  alarm_description  = "Lambda function ${each.value} approaching timeout"
  treat_missing_data = "notBreaching"

  dimensions = {
    FunctionName = each.value
  }

  alarm_actions = [aws_sns_topic.alerts[0].arn]

  tags = merge(var.tags, {
    Name   = "${each.value}-duration"
    Module = "provisioner"
  })
}
