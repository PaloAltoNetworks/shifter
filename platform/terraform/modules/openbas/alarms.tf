# OpenBAS CloudWatch Alarms
#
# Monitoring for:
# - ECS service health
# - RDS database metrics

# ------------------------------------------------------------------------------
# SNS Topic for Alerts
# ------------------------------------------------------------------------------

resource "aws_sns_topic" "openbas_alerts" {
  name = "${var.name_prefix}-openbas-alerts"

  tags = local.common_tags
}

# ------------------------------------------------------------------------------
# ECS Service Alarms
# ------------------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "ecs_cpu_high" {
  alarm_name          = "${var.name_prefix}-openbas-cpu-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "CPUUtilization"
  namespace           = "AWS/ECS"
  period              = 300
  statistic           = "Average"
  threshold           = 80
  alarm_description   = "OpenBAS ECS CPU utilization is too high"
  alarm_actions       = [aws_sns_topic.openbas_alerts.arn]
  ok_actions          = [aws_sns_topic.openbas_alerts.arn]

  dimensions = {
    ClusterName = aws_ecs_cluster.openbas.name
    ServiceName = aws_ecs_service.openbas.name
  }

  tags = local.common_tags
}

resource "aws_cloudwatch_metric_alarm" "ecs_memory_high" {
  alarm_name          = "${var.name_prefix}-openbas-memory-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "MemoryUtilization"
  namespace           = "AWS/ECS"
  period              = 300
  statistic           = "Average"
  threshold           = 80
  alarm_description   = "OpenBAS ECS memory utilization is too high"
  alarm_actions       = [aws_sns_topic.openbas_alerts.arn]
  ok_actions          = [aws_sns_topic.openbas_alerts.arn]

  dimensions = {
    ClusterName = aws_ecs_cluster.openbas.name
    ServiceName = aws_ecs_service.openbas.name
  }

  tags = local.common_tags
}

resource "aws_cloudwatch_metric_alarm" "ecs_task_count_low" {
  alarm_name          = "${var.name_prefix}-openbas-task-count-low"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 2
  metric_name         = "RunningTaskCount"
  namespace           = "ECS/ContainerInsights"
  period              = 60
  statistic           = "Average"
  threshold           = var.min_capacity
  alarm_description   = "OpenBAS running tasks below minimum"
  alarm_actions       = [aws_sns_topic.openbas_alerts.arn]
  ok_actions          = [aws_sns_topic.openbas_alerts.arn]

  dimensions = {
    ClusterName = aws_ecs_cluster.openbas.name
    ServiceName = aws_ecs_service.openbas.name
  }

  tags = local.common_tags
}

# ------------------------------------------------------------------------------
# RDS Alarms
# ------------------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "rds_cpu_high" {
  alarm_name          = "${var.name_prefix}-openbas-rds-cpu-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "CPUUtilization"
  namespace           = "AWS/RDS"
  period              = 300
  statistic           = "Average"
  threshold           = 80
  alarm_description   = "OpenBAS RDS CPU utilization is too high"
  alarm_actions       = [aws_sns_topic.openbas_alerts.arn]
  ok_actions          = [aws_sns_topic.openbas_alerts.arn]

  dimensions = {
    DBInstanceIdentifier = aws_db_instance.openbas.identifier
  }

  tags = local.common_tags
}

resource "aws_cloudwatch_metric_alarm" "rds_storage_low" {
  alarm_name          = "${var.name_prefix}-openbas-rds-storage-low"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 2
  metric_name         = "FreeStorageSpace"
  namespace           = "AWS/RDS"
  period              = 300
  statistic           = "Average"
  threshold           = 5368709120 # 5 GB in bytes
  alarm_description   = "OpenBAS RDS free storage is low"
  alarm_actions       = [aws_sns_topic.openbas_alerts.arn]
  ok_actions          = [aws_sns_topic.openbas_alerts.arn]

  dimensions = {
    DBInstanceIdentifier = aws_db_instance.openbas.identifier
  }

  tags = local.common_tags
}

resource "aws_cloudwatch_metric_alarm" "rds_connections_high" {
  alarm_name          = "${var.name_prefix}-openbas-rds-connections-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "DatabaseConnections"
  namespace           = "AWS/RDS"
  period              = 300
  statistic           = "Average"
  threshold           = 80 # Adjust based on instance class
  alarm_description   = "OpenBAS RDS connection count is high"
  alarm_actions       = [aws_sns_topic.openbas_alerts.arn]
  ok_actions          = [aws_sns_topic.openbas_alerts.arn]

  dimensions = {
    DBInstanceIdentifier = aws_db_instance.openbas.identifier
  }

  tags = local.common_tags
}
