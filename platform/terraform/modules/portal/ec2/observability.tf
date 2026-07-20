# ------------------------------------------------------------------------------
# Portal capacity observability (#940)
# ------------------------------------------------------------------------------
# Makes the autoscaling signal observable (dashboards/alarms, acceptance #940)
# and adds the additive app-saturation scale-out. Shapes mirror the Redis / SQS
# / worker-health alarm conventions: explicit period/evaluation_periods,
# statistic, low-cardinality dimensions, alarm_actions/ok_actions, tags, and an
# explicit treat_missing_data.
#
# Concept separation (do not collapse these — #851 / #940):
#   - cpu_high is now a guardrail *notification* only (SNS), never a scaling
#     action. Average EC2 CPU is no longer the portal scale-out signal.
#   - WorkerBusyRatio (Shifter/PortalCapacity) drives the additive app-saturation
#     scale-out (aws_autoscaling_policy.scale_up). treat_missing_data is
#     "notBreaching" so a missing custom-metric series fails safe (no scale
#     action), never a phantom scale-out, and crucially never a scale-in.
#   - ALB latency / 5xx / rejected-connection / unhealthy-host alarms notify.
#   - A dedicated missing-data alarm makes "the capacity control loop went blind"
#     visible to operators instead of silently degrading.

# Average EC2 CPU guardrail — notification only, not a scaling action (#940).
resource "aws_cloudwatch_metric_alarm" "cpu_high" {
  count = var.enable_autoscaling && var.enable_portal_capacity_alarms ? 1 : 0

  alarm_name          = "${var.name_prefix}-cpu-high"
  alarm_description   = "Guardrail: portal average EC2 CPU > ${var.scale_up_threshold}% on ${var.name_prefix} (notification only; scaling is request-path driven, #940)"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "CPUUtilization"
  namespace           = "AWS/EC2"
  period              = 120
  statistic           = "Average"
  threshold           = var.scale_up_threshold
  treat_missing_data  = "notBreaching"

  dimensions = {
    AutoScalingGroupName = aws_autoscaling_group.this[0].name
  }

  alarm_actions = var.portal_capacity_alarm_actions
  ok_actions    = var.portal_capacity_alarm_actions

  tags = merge(local.common_tags, { Name = "${var.name_prefix}-cpu-high" })
}

# Additive app-saturation scale-out: the hottest portal web worker's busy ratio
# crossing the threshold scales the ASG out by one (aws_autoscaling_policy
# scale_up). Maximum picks the hottest worker so a single pinned worker can drive
# capacity even when the fleet mean looks calm.
resource "aws_cloudwatch_metric_alarm" "worker_busy_ratio_high" {
  count = var.enable_autoscaling && var.enable_portal_capacity_alarms ? 1 : 0

  alarm_name          = "${var.name_prefix}-worker-busy-ratio-high"
  alarm_description   = "Portal web worker busy ratio (hottest worker) > ${var.worker_busy_ratio_scale_out_threshold} on ${var.name_prefix}: app-saturation scale-out (#940)"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "WorkerBusyRatio"
  namespace           = "Shifter/PortalCapacity"
  period              = 60
  statistic           = "Maximum"
  threshold           = var.worker_busy_ratio_scale_out_threshold
  # Fail safe: a missing custom-metric series must never imply saturation, so it
  # never triggers a phantom scale-out (and is never a scale-in input at all).
  treat_missing_data = "notBreaching"

  dimensions = {
    NamePrefix = var.name_prefix
  }

  alarm_actions = concat([aws_autoscaling_policy.scale_up[0].arn], var.portal_capacity_alarm_actions)

  tags = merge(local.common_tags, { Name = "${var.name_prefix}-worker-busy-ratio-high" })
}

# The capacity control loop is blind if the app stops publishing PortalCapacity
# metrics (deploy gap, failed import, CloudWatch outage). Surface that to
# operators rather than letting a silent gap masquerade as "calm".
resource "aws_cloudwatch_metric_alarm" "portal_capacity_missing" {
  count = var.enable_autoscaling && var.enable_portal_capacity_alarms ? 1 : 0

  alarm_name          = "${var.name_prefix}-portal-capacity-metrics-missing"
  alarm_description   = "Portal capacity metrics (Shifter/PortalCapacity) stopped reporting on ${var.name_prefix}: autoscaling saturation visibility is degraded (#940)"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 5
  metric_name         = "WorkerInFlightRequests"
  namespace           = "Shifter/PortalCapacity"
  period              = 60
  statistic           = "SampleCount"
  threshold           = 1
  # Breaching on missing data is the point: no samples == the emitter is silent.
  treat_missing_data = "breaching"

  dimensions = {
    NamePrefix = var.name_prefix
  }

  alarm_actions = var.portal_capacity_alarm_actions
  ok_actions    = var.portal_capacity_alarm_actions

  tags = merge(local.common_tags, { Name = "${var.name_prefix}-portal-capacity-metrics-missing" })
}

# ALB-side request-path observability. These notify operators; they are not
# scaling actions (the target-tracking policies already react to the same
# signals). Valid in both single-instance and ASG mode since the ALB exists in
# both, so they are gated on alarms-enabled alone.
resource "aws_cloudwatch_metric_alarm" "alb_target_response_time_high" {
  count = var.enable_portal_capacity_alarms ? 1 : 0

  alarm_name          = "${var.name_prefix}-alb-target-response-time-high"
  alarm_description   = "Portal ALB p95 target response time > ${var.target_response_time_alarm_threshold_seconds}s on ${var.name_prefix} (#940)"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "TargetResponseTime"
  namespace           = "AWS/ApplicationELB"
  period              = 60
  extended_statistic  = "p95"
  threshold           = var.target_response_time_alarm_threshold_seconds
  treat_missing_data  = "notBreaching"

  dimensions = {
    LoadBalancer = var.alb_arn_suffix
    TargetGroup  = var.target_group_arn_suffix
  }

  alarm_actions = var.portal_capacity_alarm_actions
  ok_actions    = var.portal_capacity_alarm_actions

  tags = merge(local.common_tags, { Name = "${var.name_prefix}-alb-target-response-time-high" })
}

resource "aws_cloudwatch_metric_alarm" "alb_target_5xx_high" {
  count = var.enable_portal_capacity_alarms ? 1 : 0

  alarm_name          = "${var.name_prefix}-alb-target-5xx-high"
  alarm_description   = "Portal ALB target 5xx responses elevated on ${var.name_prefix} (#940)"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "HTTPCode_Target_5XX_Count"
  namespace           = "AWS/ApplicationELB"
  period              = 60
  statistic           = "Sum"
  threshold           = var.alb_target_5xx_alarm_threshold
  treat_missing_data  = "notBreaching"

  dimensions = {
    LoadBalancer = var.alb_arn_suffix
    TargetGroup  = var.target_group_arn_suffix
  }

  alarm_actions = var.portal_capacity_alarm_actions
  ok_actions    = var.portal_capacity_alarm_actions

  tags = merge(local.common_tags, { Name = "${var.name_prefix}-alb-target-5xx-high" })
}

resource "aws_cloudwatch_metric_alarm" "alb_rejected_connections" {
  count = var.enable_portal_capacity_alarms ? 1 : 0

  alarm_name          = "${var.name_prefix}-alb-rejected-connections"
  alarm_description   = "Portal ALB rejected connections (admission saturation) on ${var.name_prefix} (#940)"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "RejectedConnectionCount"
  namespace           = "AWS/ApplicationELB"
  period              = 60
  statistic           = "Sum"
  threshold           = 0
  treat_missing_data  = "notBreaching"

  dimensions = {
    LoadBalancer = var.alb_arn_suffix
  }

  alarm_actions = var.portal_capacity_alarm_actions
  ok_actions    = var.portal_capacity_alarm_actions

  tags = merge(local.common_tags, { Name = "${var.name_prefix}-alb-rejected-connections" })
}

resource "aws_cloudwatch_metric_alarm" "alb_unhealthy_hosts" {
  count = var.enable_portal_capacity_alarms ? 1 : 0

  alarm_name          = "${var.name_prefix}-alb-unhealthy-hosts"
  alarm_description   = "Portal ALB target group has unhealthy hosts on ${var.name_prefix} (#940)"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "UnHealthyHostCount"
  namespace           = "AWS/ApplicationELB"
  period              = 60
  statistic           = "Maximum"
  threshold           = 0
  treat_missing_data  = "notBreaching"

  dimensions = {
    LoadBalancer = var.alb_arn_suffix
    TargetGroup  = var.target_group_arn_suffix
  }

  alarm_actions = var.portal_capacity_alarm_actions
  ok_actions    = var.portal_capacity_alarm_actions

  tags = merge(local.common_tags, { Name = "${var.name_prefix}-alb-unhealthy-hosts" })
}

# Single-pane dashboard of the scaling signal and the app-saturation gauges it is
# meant to replace CPU with. ASG-dimensioned, so gated on ASG mode.
resource "aws_cloudwatch_dashboard" "portal_capacity" {
  count = var.enable_autoscaling && var.enable_portal_capacity_alarms ? 1 : 0

  dashboard_name = "${var.name_prefix}-portal-capacity"

  dashboard_body = jsonencode({
    widgets = [
      {
        type   = "metric"
        x      = 0
        y      = 0
        width  = 12
        height = 6
        properties = {
          title  = "ALB RequestCountPerTarget (scale-out signal)"
          region = data.aws_region.current.name
          view   = "timeSeries"
          stat   = "Sum"
          period = 60
          # RequestCountPerTarget is published under the LoadBalancer + TargetGroup
          # dimension pair (Per AppELB, per TG), not TargetGroup alone.
          metrics = [
            ["AWS/ApplicationELB", "RequestCountPerTarget", "TargetGroup", var.target_group_arn_suffix, "LoadBalancer", var.alb_arn_suffix]
          ]
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 0
        width  = 12
        height = 6
        properties = {
          title  = "ALB TargetResponseTime p95 (queueing proxy)"
          region = data.aws_region.current.name
          view   = "timeSeries"
          stat   = "p95"
          period = 60
          metrics = [
            ["AWS/ApplicationELB", "TargetResponseTime", "LoadBalancer", var.alb_arn_suffix, "TargetGroup", var.target_group_arn_suffix]
          ]
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 6
        width  = 12
        height = 6
        properties = {
          title  = "Portal worker busy ratio (mean vs hottest)"
          region = data.aws_region.current.name
          view   = "timeSeries"
          period = 60
          metrics = [
            ["Shifter/PortalCapacity", "WorkerBusyRatio", "NamePrefix", var.name_prefix, { stat = "Average", label = "fleet mean" }],
            ["...", { stat = "Maximum", label = "hottest worker" }]
          ]
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 6
        width  = 12
        height = 6
        properties = {
          title  = "Portal terminal sessions (fleet) and EC2 CPU guardrail"
          region = data.aws_region.current.name
          view   = "timeSeries"
          period = 60
          metrics = [
            ["Shifter/PortalCapacity", "TerminalActiveSessions", "NamePrefix", var.name_prefix, { stat = "Sum", label = "terminal sessions" }],
            ["AWS/EC2", "CPUUtilization", "AutoScalingGroupName", aws_autoscaling_group.this[0].name, { stat = "Average", label = "EC2 CPU (guardrail)" }]
          ]
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 12
        width  = 24
        height = 6
        properties = {
          title  = "ALB errors and ASG in-service capacity"
          region = data.aws_region.current.name
          view   = "timeSeries"
          period = 60
          metrics = [
            ["AWS/ApplicationELB", "HTTPCode_Target_5XX_Count", "LoadBalancer", var.alb_arn_suffix, "TargetGroup", var.target_group_arn_suffix, { stat = "Sum", label = "target 5xx" }],
            ["AWS/ApplicationELB", "RejectedConnectionCount", "LoadBalancer", var.alb_arn_suffix, { stat = "Sum", label = "rejected connections" }],
            ["AWS/AutoScaling", "GroupInServiceInstances", "AutoScalingGroupName", aws_autoscaling_group.this[0].name, { stat = "Average", label = "in-service instances" }]
          ]
        }
      }
    ]
  })
}
