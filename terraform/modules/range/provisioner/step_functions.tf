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
        Type = "Fail"
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
