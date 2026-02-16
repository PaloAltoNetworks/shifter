# Redis Module - ElastiCache for Django Channels
#
# Creates:
# - ElastiCache subnet group
# - Security group for Redis
# - ElastiCache Redis cluster (single-node or replication group)

# ------------------------------------------------------------------------------
# Subnet Group
# ------------------------------------------------------------------------------

resource "aws_elasticache_subnet_group" "this" {
  name       = "${var.name_prefix}-redis"
  subnet_ids = var.subnet_ids

  tags = merge(var.tags, {
    Name   = "${var.name_prefix}-redis-subnet-group"
    Module = "redis"
  })
}

# ------------------------------------------------------------------------------
# Security Group for Redis
# ------------------------------------------------------------------------------

resource "aws_security_group" "this" {
  name        = "${var.name_prefix}-redis-sg"
  description = "Security group for ElastiCache Redis"
  vpc_id      = var.vpc_id

  tags = merge(var.tags, {
    Name   = "${var.name_prefix}-redis-sg"
    Module = "redis"
  })
}

resource "aws_security_group_rule" "ingress_redis" {
  type              = "ingress"
  from_port         = 6379
  to_port           = 6379
  protocol          = "tcp"
  cidr_blocks       = var.allowed_cidr_blocks
  security_group_id = aws_security_group.this.id
  description       = "Redis access"
}

resource "aws_security_group_rule" "egress_all" {
  type              = "egress"
  from_port         = 0
  to_port           = 0
  protocol          = "-1"
  cidr_blocks       = ["0.0.0.0/0"]
  security_group_id = aws_security_group.this.id
  description       = "Allow all outbound"
}

# ------------------------------------------------------------------------------
# ElastiCache Redis - Single Node (dev)
# ------------------------------------------------------------------------------

# checkov:skip=CKV_AWS_31:Redis encryption at rest deferred - internal VPC only, see #295
# checkov:skip=CKV_AWS_30:Redis encryption in transit deferred - internal VPC only, see #295
resource "aws_elasticache_cluster" "single_node" {
  count = var.enable_replication ? 0 : 1

  cluster_id           = "${var.name_prefix}-redis"
  engine               = "redis"
  engine_version       = var.engine_version
  node_type            = var.node_type
  num_cache_nodes      = 1
  parameter_group_name = "default.redis7"
  port                 = 6379

  subnet_group_name  = aws_elasticache_subnet_group.this.name
  security_group_ids = [aws_security_group.this.id]

  # Maintenance window (UTC) - Sunday 3-4 AM
  maintenance_window = "sun:03:00-sun:04:00"

  # Snapshot retention disabled for single-node (not supported)
  snapshot_retention_limit = 0

  tags = merge(var.tags, {
    Name   = "${var.name_prefix}-redis"
    Module = "redis"
  })
}

# ------------------------------------------------------------------------------
# ElastiCache Redis - Replication Group (prod)
# ------------------------------------------------------------------------------

# checkov:skip=CKV_AWS_31:Redis encryption at rest deferred - internal VPC only, see #295
# checkov:skip=CKV_AWS_30:Redis encryption in transit deferred - internal VPC only, see #295
resource "aws_elasticache_replication_group" "ha" {
  count = var.enable_replication ? 1 : 0

  replication_group_id = "${var.name_prefix}-redis"
  description          = "Redis replication group for ${var.name_prefix}"
  engine               = "redis"
  engine_version       = var.engine_version
  node_type            = var.node_type
  port                 = 6379
  parameter_group_name = "default.redis7"

  automatic_failover_enabled = true
  multi_az_enabled           = true
  num_cache_clusters         = 2

  subnet_group_name  = aws_elasticache_subnet_group.this.name
  security_group_ids = [aws_security_group.this.id]

  maintenance_window       = "sun:03:00-sun:04:00"
  snapshot_retention_limit = 1
  snapshot_window          = "01:00-02:00"

  at_rest_encryption_enabled = false
  transit_encryption_enabled = false

  tags = merge(var.tags, {
    Name   = "${var.name_prefix}-redis"
    Module = "redis"
  })
}

# ------------------------------------------------------------------------------
# CloudWatch Alarms
# ------------------------------------------------------------------------------

locals {
  # Get the cache cluster ID for alarms - depends on mode
  # For replication group, use the replication group ID
  # For single node, use the cluster ID
  cluster_id = var.enable_replication ? aws_elasticache_replication_group.ha[0].id : aws_elasticache_cluster.single_node[0].cluster_id
}

# CPU Utilization Alarm
resource "aws_cloudwatch_metric_alarm" "cpu" {
  count = var.enable_alarms ? 1 : 0

  alarm_name          = "${var.name_prefix}-redis-cpu-utilization"
  alarm_description   = "Redis CPU utilization is above ${var.alarm_cpu_threshold}%"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "CPUUtilization"
  namespace           = "AWS/ElastiCache"
  period              = 300
  statistic           = "Average"
  threshold           = var.alarm_cpu_threshold

  dimensions = {
    CacheClusterId = local.cluster_id
  }

  alarm_actions = var.alarm_actions
  ok_actions    = var.alarm_actions

  tags = merge(var.tags, {
    Name   = "${var.name_prefix}-redis-cpu-alarm"
    Module = "redis"
  })
}

# Memory Utilization Alarm (DatabaseMemoryUsagePercentage)
resource "aws_cloudwatch_metric_alarm" "memory" {
  count = var.enable_alarms ? 1 : 0

  alarm_name          = "${var.name_prefix}-redis-memory-utilization"
  alarm_description   = "Redis memory utilization is above ${var.alarm_memory_threshold}%"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "DatabaseMemoryUsagePercentage"
  namespace           = "AWS/ElastiCache"
  period              = 300
  statistic           = "Average"
  threshold           = var.alarm_memory_threshold

  dimensions = {
    CacheClusterId = local.cluster_id
  }

  alarm_actions = var.alarm_actions
  ok_actions    = var.alarm_actions

  tags = merge(var.tags, {
    Name   = "${var.name_prefix}-redis-memory-alarm"
    Module = "redis"
  })
}

# Current Connections Alarm
resource "aws_cloudwatch_metric_alarm" "connections" {
  count = var.enable_alarms ? 1 : 0

  alarm_name          = "${var.name_prefix}-redis-connections"
  alarm_description   = "Redis connections exceed ${var.alarm_connections_threshold}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "CurrConnections"
  namespace           = "AWS/ElastiCache"
  period              = 300
  statistic           = "Average"
  threshold           = var.alarm_connections_threshold

  dimensions = {
    CacheClusterId = local.cluster_id
  }

  alarm_actions = var.alarm_actions
  ok_actions    = var.alarm_actions

  tags = merge(var.tags, {
    Name   = "${var.name_prefix}-redis-connections-alarm"
    Module = "redis"
  })
}
