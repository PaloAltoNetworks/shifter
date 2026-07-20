# ------------------------------------------------------------------------------
# Runner health alarms (#292)
# ------------------------------------------------------------------------------
# Five separate signals, kept distinct per the preflight note:
#   1. EC2 instance status check   (native AWS/EC2)        -> notify
#   2. EC2 system status check     (native AWS/EC2)        -> notify + opt-in recover
#   3. Sustained CPU saturation    (native AWS/EC2)        -> notify (hang proxy)
#   4. Runner systemd-service down (Shifter/RunnerHealth)  -> notify; missing data
#                                                             is breaching so a
#                                                             hung host that stops
#                                                             publishing alarms.
# SSM reachability is covered by signal 4: a host that cannot be SSM-managed has
# also stopped publishing its heartbeat. Exact SSM PingStatus polling and
# GitHub-API runner-online status are deferred (see the runbook); both need
# either a Lambda or a long-lived credential and are out of scope here.
#
# Each alarm is created per runner (count = var.runner_count) and derives its
# dimension from aws_instance.runner / the runner name, never a hard-coded
# instance id.

locals {
  runner_alarm_actions = [aws_sns_topic.runner_alerts.arn]
}

# SNS topic owned by this root (engine-provisioner idiom). Alarm actions always
# target the topic; notifications deliver once a subscription exists. Email is an
# optional subscription; Slack/Teams subscribe to the topic via the account's
# approved integration without changing any alarm resource.
resource "aws_sns_topic" "runner_alerts" {
  name              = "shifter-github-runner-alerts"
  kms_master_key_id = "alias/aws/sns"

  tags = {
    Name = "shifter-github-runner-alerts"
  }
}

resource "aws_sns_topic_subscription" "runner_alerts_email" {
  count = var.alarm_email != "" ? 1 : 0

  topic_arn = aws_sns_topic.runner_alerts.arn
  protocol  = "email"
  endpoint  = var.alarm_email
}

# 1. EC2 instance status check (reachability of the guest OS / instance).
resource "aws_cloudwatch_metric_alarm" "runner_status_check_instance" {
  count = var.runner_count

  alarm_name          = "shifter-github-runner-${count.index + 1}-status-check-instance"
  alarm_description   = "Instance status check failing on shifter-github-runner-${count.index + 1} (guest OS / network unreachable)."
  namespace           = "AWS/EC2"
  metric_name         = "StatusCheckFailed_Instance"
  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  evaluation_periods  = 2
  period              = 60
  statistic           = "Maximum"
  treat_missing_data  = "notBreaching"

  dimensions = {
    InstanceId = aws_instance.runner[count.index].id
  }

  alarm_actions = local.runner_alarm_actions
  ok_actions    = local.runner_alarm_actions

  tags = {
    Name = "shifter-github-runner-${count.index + 1}-status-check-instance"
  }
}

# 2. EC2 system status check (underlying AWS hardware). The only signal allowed
# to auto-recover, and only when var.enable_system_auto_recovery is set; recover
# moves the instance to healthy hardware while preserving its id, EBS, and IP.
resource "aws_cloudwatch_metric_alarm" "runner_status_check_system" {
  count = var.runner_count

  alarm_name          = "shifter-github-runner-${count.index + 1}-status-check-system"
  alarm_description   = "System status check failing on shifter-github-runner-${count.index + 1} (AWS hardware fault)."
  namespace           = "AWS/EC2"
  metric_name         = "StatusCheckFailed_System"
  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  evaluation_periods  = 2
  period              = 60
  statistic           = "Maximum"
  treat_missing_data  = "notBreaching"

  dimensions = {
    InstanceId = aws_instance.runner[count.index].id
  }

  alarm_actions = concat(
    local.runner_alarm_actions,
    var.enable_system_auto_recovery ? ["arn:aws:automate:${var.region}:ec2:recover"] : [],
  )
  ok_actions = local.runner_alarm_actions

  tags = {
    Name = "shifter-github-runner-${count.index + 1}-status-check-system"
  }
}

# 3. Sustained CPU saturation as a hang proxy. Two 5-minute periods (10 min) so a
# normal build spike does not page; a wedged host pegged at 100% does.
resource "aws_cloudwatch_metric_alarm" "runner_cpu_high" {
  count = var.runner_count

  alarm_name          = "shifter-github-runner-${count.index + 1}-cpu-high"
  alarm_description   = "Sustained high CPU on shifter-github-runner-${count.index + 1} (possible hang)."
  namespace           = "AWS/EC2"
  metric_name         = "CPUUtilization"
  comparison_operator = "GreaterThanThreshold"
  threshold           = var.cpu_alarm_threshold
  evaluation_periods  = 2
  period              = 300
  statistic           = "Average"
  treat_missing_data  = "notBreaching"

  dimensions = {
    InstanceId = aws_instance.runner[count.index].id
  }

  alarm_actions = local.runner_alarm_actions
  ok_actions    = local.runner_alarm_actions

  tags = {
    Name = "shifter-github-runner-${count.index + 1}-cpu-high"
  }
}

# 4. Runner systemd-service liveness. The host monitor publishes 1 while the
# actions.runner.* service is active and 0 when it is not. Missing data is
# breaching: a hung host cannot run the monitor, so the absence of the heartbeat
# is itself the hung-host signal (the actual #292 incident).
resource "aws_cloudwatch_metric_alarm" "runner_service_inactive" {
  count = var.runner_count

  alarm_name          = "shifter-github-runner-${count.index + 1}-service-inactive"
  alarm_description   = "Runner service inactive or host not reporting on shifter-github-runner-${count.index + 1}."
  namespace           = "Shifter/RunnerHealth"
  metric_name         = "RunnerServiceActive"
  comparison_operator = "LessThanThreshold"
  threshold           = 1
  evaluation_periods  = 2
  period              = 60
  statistic           = "Minimum"
  treat_missing_data  = "breaching"

  dimensions = {
    RunnerName = "shifter-github-runner-${count.index + 1}"
  }

  alarm_actions = local.runner_alarm_actions
  ok_actions    = local.runner_alarm_actions

  tags = {
    Name = "shifter-github-runner-${count.index + 1}-service-inactive"
  }
}
