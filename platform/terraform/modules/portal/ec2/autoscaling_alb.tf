# ------------------------------------------------------------------------------
# ALB-metric-driven autoscaling (#940)
# ------------------------------------------------------------------------------
# The portal serves ~4 serialized sync requests per worker, so saturation shows
# up as request queueing latency that average EC2 CPU never reflects (#851 /
# #940). These two target-tracking policies make scale-out a function of
# request-path saturation and reach scale-out before CPU pins:
#
#   - ALBRequestCountPerTarget: requests-per-target is the leading traffic
#     signal. It is an AWS-predefined target-tracking metric; the resource_label
#     is "<alb-arn-suffix>/<target-group-arn-suffix>".
#   - TargetResponseTime: the cheap leading proxy for queueing. It has no
#     predefined metric type, so it is expressed as a customized metric
#     specification (Average latency in seconds).
#
# Target tracking owns both directions: it scales out on saturation and scales
# in only when the saturation signals are low, which is the saturation-aware,
# drain-respecting scale-in the #940 preflight requires (it will not scale in
# while either signal is high, so it never drops a busy-but-low-CPU fleet).
# These are AWS-native, always-present signals, so unlike the app-emitted
# Shifter/PortalCapacity gauges they can never go missing and scale a fleet
# blind. estimated_instance_warmup matches the launch lifecycle-hook window so a
# still-booting instance is not counted before it serves traffic.

resource "aws_autoscaling_policy" "alb_request_count" {
  count = var.enable_autoscaling ? 1 : 0

  name                      = "${var.name_prefix}-alb-request-count-tracking"
  autoscaling_group_name    = aws_autoscaling_group.this[0].name
  policy_type               = "TargetTrackingScaling"
  estimated_instance_warmup = var.lifecycle_hook_heartbeat_timeout

  target_tracking_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ALBRequestCountPerTarget"
      resource_label         = "${var.alb_arn_suffix}/${var.target_group_arn_suffix}"
    }
    target_value = var.scale_target_requests_per_target
  }
}

resource "aws_autoscaling_policy" "alb_response_time" {
  count = var.enable_autoscaling ? 1 : 0

  name                      = "${var.name_prefix}-alb-response-time-tracking"
  autoscaling_group_name    = aws_autoscaling_group.this[0].name
  policy_type               = "TargetTrackingScaling"
  estimated_instance_warmup = var.lifecycle_hook_heartbeat_timeout

  target_tracking_configuration {
    customized_metric_specification {
      metric_name = "TargetResponseTime"
      namespace   = "AWS/ApplicationELB"
      statistic   = "Average"

      metric_dimension {
        name  = "LoadBalancer"
        value = var.alb_arn_suffix
      }
      metric_dimension {
        name  = "TargetGroup"
        value = var.target_group_arn_suffix
      }
    }
    target_value = var.scale_target_response_time_seconds
  }
}
