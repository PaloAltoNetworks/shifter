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
          aws_lambda_function.configure_librechat.arn,
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

  definition = jsonencode({
    Comment = "Provision a new range with subnet, victim, kali, and librechat"
    StartAt = "CreateSubnet"
    # Timeout after 30 minutes to prevent runaway executions
    TimeoutSeconds = 1800
    States = {
      CreateSubnet = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = aws_lambda_function.create_subnet.arn
          Payload = {
            "range_id.$" = "$.range_id"
          }
        }
        ResultPath = "$.create_subnet_result"
        ResultSelector = {
          "subnet_id.$"   = "$.Payload.subnet_id"
          "subnet_cidr.$" = "$.Payload.subnet_cidr"
        }
        Next = "CreateVictim"
        Catch = [
          {
            ErrorEquals = ["States.ALL"]
            ResultPath  = "$.error"
            Next        = "Cleanup"
          }
        ]
        Retry = [
          {
            ErrorEquals     = ["Lambda.ServiceException", "Lambda.TooManyRequestsException"]
            IntervalSeconds = 2
            MaxAttempts     = 3
            BackoffRate     = 2
          }
        ]
      }

      CreateVictim = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = aws_lambda_function.create_victim.arn
          Payload = {
            "range_id.$" = "$.range_id"
          }
        }
        ResultPath = "$.create_victim_result"
        ResultSelector = {
          "victim_instance_id.$" = "$.Payload.victim_instance_id"
          "victim_ip.$"          = "$.Payload.victim_ip"
        }
        Next = "CreateKali"
        Catch = [
          {
            ErrorEquals = ["States.ALL"]
            ResultPath  = "$.error"
            Next        = "Cleanup"
          }
        ]
        Retry = [
          {
            ErrorEquals     = ["Lambda.ServiceException", "Lambda.TooManyRequestsException"]
            IntervalSeconds = 2
            MaxAttempts     = 3
            BackoffRate     = 2
          }
        ]
      }

      CreateKali = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = aws_lambda_function.create_kali.arn
          Payload = {
            "range_id.$" = "$.range_id"
          }
        }
        ResultPath = "$.create_kali_result"
        ResultSelector = {
          "kali_info.$" = "$.Payload.kali_info"
        }
        Next = "ConfigureLibreChat"
        Catch = [
          {
            ErrorEquals = ["States.ALL"]
            ResultPath  = "$.error"
            Next        = "Cleanup"
          }
        ]
        Retry = [
          {
            ErrorEquals     = ["Lambda.ServiceException", "Lambda.TooManyRequestsException"]
            IntervalSeconds = 2
            MaxAttempts     = 3
            BackoffRate     = 2
          }
        ]
      }

      ConfigureLibreChat = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = aws_lambda_function.configure_librechat.arn
          Payload = {
            "range_id.$" = "$.range_id"
          }
        }
        ResultPath = "$.configure_librechat_result"
        ResultSelector = {
          "chat_url.$" = "$.Payload.chat_url"
        }
        Next = "Success"
        Catch = [
          {
            ErrorEquals = ["States.ALL"]
            ResultPath  = "$.error"
            Next        = "Cleanup"
          }
        ]
        Retry = [
          {
            ErrorEquals     = ["Lambda.ServiceException", "Lambda.TooManyRequestsException"]
            IntervalSeconds = 2
            MaxAttempts     = 3
            BackoffRate     = 2
          }
        ]
      }

      Cleanup = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = aws_lambda_function.cleanup.arn
          Payload = {
            "range_id.$"    = "$.range_id"
            "mark_failed"   = true
            "error_message" = "Provisioning failed - resources cleaned up"
          }
        }
        ResultPath = "$.cleanup_result"
        Next       = "Failed"
        Retry = [
          {
            ErrorEquals     = ["States.ALL"]
            IntervalSeconds = 5
            MaxAttempts     = 3
            BackoffRate     = 2
          }
        ]
      }

      Success = {
        Type = "Succeed"
      }

      Failed = {
        Type  = "Fail"
        Error = "ProvisioningFailed"
        Cause = "Range provisioning failed, resources have been cleaned up"
      }
    }
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

  definition = jsonencode({
    Comment = "Teardown an existing range - destroy all resources"
    StartAt = "Cleanup"
    # Timeout after 15 minutes
    TimeoutSeconds = 900
    States = {
      Cleanup = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = aws_lambda_function.cleanup.arn
          Payload = {
            "range_id.$"  = "$.range_id"
            "mark_failed" = false
          }
        }
        ResultPath = "$.cleanup_result"
        ResultSelector = {
          "cleaned_up.$" = "$.Payload.cleaned_up"
        }
        Next = "Success"
        Retry = [
          {
            ErrorEquals     = ["States.ALL"]
            IntervalSeconds = 5
            MaxAttempts     = 5
            BackoffRate     = 2
          }
        ]
        Catch = [
          {
            ErrorEquals = ["States.ALL"]
            ResultPath  = "$.error"
            Next        = "Failed"
          }
        ]
      }

      Success = {
        Type = "Succeed"
      }

      Failed = {
        Type  = "Fail"
        Error = "TeardownFailed"
        Cause = "Range teardown failed"
      }
    }
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

  definition = jsonencode({
    Comment = "Find and clean up stale ranges stuck in transitional states"
    StartAt = "FindStaleRanges"
    # Timeout after 30 minutes
    TimeoutSeconds = 1800
    States = {
      FindStaleRanges = {
        Type     = "Task"
        Resource = "arn:aws:states:::lambda:invoke"
        Parameters = {
          FunctionName = aws_lambda_function.find_stale_ranges.arn
          Payload      = {}
        }
        ResultPath = "$.find_result"
        ResultSelector = {
          "stale_ranges.$" = "$.Payload.stale_ranges"
          "checked_at.$"   = "$.Payload.checked_at"
        }
        Next = "CheckForStaleRanges"
        Retry = [
          {
            ErrorEquals     = ["Lambda.ServiceException", "Lambda.TooManyRequestsException"]
            IntervalSeconds = 2
            MaxAttempts     = 3
            BackoffRate     = 2
          }
        ]
        Catch = [
          {
            ErrorEquals = ["States.ALL"]
            ResultPath  = "$.error"
            Next        = "Failed"
          }
        ]
      }

      CheckForStaleRanges = {
        Type = "Choice"
        Choices = [
          {
            Variable  = "$.find_result.stale_ranges[0]"
            IsPresent = true
            Next      = "CleanupStaleRanges"
          }
        ]
        Default = "NoStaleRanges"
      }

      CleanupStaleRanges = {
        Type           = "Map"
        ItemsPath      = "$.find_result.stale_ranges"
        MaxConcurrency = 2
        ItemProcessor = {
          ProcessorConfig = {
            Mode = "INLINE"
          }
          StartAt = "CleanupRange"
          States = {
            CleanupRange = {
              Type     = "Task"
              Resource = "arn:aws:states:::lambda:invoke"
              Parameters = {
                FunctionName = aws_lambda_function.cleanup.arn
                Payload = {
                  "range_id.$"    = "$.range_id"
                  "mark_failed"   = true
                  "error_message" = "Stale range cleanup - stuck in transitional state"
                }
              }
              ResultPath = "$.cleanup_result"
              End        = true
              Retry = [
                {
                  ErrorEquals     = ["States.ALL"]
                  IntervalSeconds = 5
                  MaxAttempts     = 3
                  BackoffRate     = 2
                }
              ]
            }
          }
        }
        ResultPath = "$.cleanup_results"
        Next       = "Success"
        Catch = [
          {
            ErrorEquals = ["States.ALL"]
            ResultPath  = "$.error"
            Next        = "Failed"
          }
        ]
      }

      NoStaleRanges = {
        Type = "Succeed"
      }

      Success = {
        Type = "Succeed"
      }

      Failed = {
        Type  = "Fail"
        Error = "StaleCleanupFailed"
        Cause = "Stale range cleanup failed"
      }
    }
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
