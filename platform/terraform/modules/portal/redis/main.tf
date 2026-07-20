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
  count = length(var.allowed_cidr_blocks) > 0 ? 1 : 0

  type              = "ingress"
  from_port         = 6379
  to_port           = 6379
  protocol          = "tcp"
  cidr_blocks       = var.allowed_cidr_blocks
  security_group_id = aws_security_group.this.id
  description       = "Redis access (CIDR-based)"
}

resource "aws_security_group_rule" "ingress_redis_sg" {
  count = length(var.allowed_security_group_ids)

  type                     = "ingress"
  from_port                = 6379
  to_port                  = 6379
  protocol                 = "tcp"
  source_security_group_id = var.allowed_security_group_ids[count.index]
  security_group_id        = aws_security_group.this.id
  description              = "Redis access (SG-based)"
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
# Threat-model acceptance (#938): this single-node path retains plaintext Redis
# with no AUTH. Posture: dev-only / private-subnet. The `aws_elasticache_cluster`
# resource cannot carry an AUTH token (AUTH requires the replication-group path),
# and this path is never the live Django Channels backend in a deployed
# environment — dev sets enable_redis = false (in-memory channels), so the
# single node is provisioned but unused, and the precondition below rejects any
# attempt to make it the active backend. Rationale: a single-tenant, private-
# subnet dev cache carrying no session-adjacent production traffic does not
# warrant the replication-group cost/replacement. Scope: dev only. Owner:
# @Brad-Edwards. Review trigger: if a deployed environment ever sets
# enable_replication = false with enable_redis = true, switch this path to the
# hardened replication group instead of accepting plaintext.
# checkov:skip=CKV_AWS_31:Single-node Redis at-rest encryption deferred - dev-only/private-subnet acceptance (#938); principled deferral via ADR-004-R11 exception (#938).
# checkov:skip=CKV_AWS_30:Single-node Redis in-transit encryption deferred - dev-only/private-subnet acceptance (#938); principled deferral via ADR-004-R11 exception (#938).
resource "aws_elasticache_cluster" "single_node" {
  count = var.enable_replication ? 0 : 1

  cluster_id           = "${var.name_prefix}-redis"
  engine               = "redis"
  engine_version       = var.engine_version
  node_type            = var.node_type
  apply_immediately    = var.apply_immediately
  num_cache_nodes      = 1
  parameter_group_name = "default.redis7"
  port                 = 6379

  subnet_group_name  = aws_elasticache_subnet_group.this.name
  security_group_ids = [aws_security_group.this.id]

  # Maintenance window (UTC) - Sunday 3-4 AM
  maintenance_window = "sun:03:00-sun:04:00"

  # Daily snapshot (CKV_AWS_134). Mirrors the replication-group window.
  snapshot_retention_limit = 1
  snapshot_window          = "01:00-02:00"

  tags = merge(var.tags, {
    Name   = "${var.name_prefix}-redis"
    Module = "redis"
  })

  lifecycle {
    precondition {
      condition     = length(var.allowed_security_group_ids) > 0 || length(var.allowed_cidr_blocks) > 0
      error_message = "portal/redis: at least one of allowed_security_group_ids or allowed_cidr_blocks must be non-empty so the Redis security group has an ingress source."
    }
    precondition {
      condition     = !var.is_active_channel_backend
      error_message = "portal/redis: is_active_channel_backend (enable_redis) requires the AUTH + in-transit encryption path (enable_replication = true). The single-node plaintext path must not back a live Django Channels layer; see the threat-model acceptance block above."
    }
  }
}

# ------------------------------------------------------------------------------
# Redis AUTH token (replication-group / in-transit-encryption path only, #938)
# ------------------------------------------------------------------------------
# ElastiCache AUTH requires in-transit encryption and is only available on the
# replication-group resource. The token is generated here and stored in Secrets
# Manager under the portal CMK; entrypoint.sh hydrates it into REDIS_PASSWORD at
# container start (same model as the DB credential secret). The single-node path
# cannot carry an AUTH token (see its acceptance block below) so these resources
# are gated on enable_replication.
#
# special = false keeps the token within the ElastiCache AUTH-token charset
# (printable ASCII excluding '/', '"', '@', and space); 64 alphanumeric chars is
# well above the 16-char minimum.
resource "random_password" "redis_auth" {
  count = var.enable_replication ? 1 : 0

  length  = 64
  special = false
}

resource "aws_secretsmanager_secret" "redis_auth" {
  count = var.enable_replication ? 1 : 0

  # CKV2_AWS_57 (rotation configured): satisfied by aws_secretsmanager_secret_rotation
  # in rotation.tf (#159) — a custom Lambda rotates the AUTH token via the
  # ElastiCache ROTATE strategy.
  name                    = "shifter-${var.name_prefix}-redis-auth"
  description             = "Redis AUTH token for the portal Django Channels backbone (#938)"
  recovery_window_in_days = 0 # Immediate deletion, avoids naming conflicts on recreate (matches RDS/app secrets)
  kms_key_id              = var.secrets_kms_key_arn

  tags = merge(var.tags, {
    Name   = "shifter-${var.name_prefix}-redis-auth"
    Module = "redis"
  })
}

# Payload shape mirrors the GCP Memorystore secret consumed by entrypoint.sh:
# {"password": <token>}. server_ca_cert is intentionally omitted — AWS
# ElastiCache presents a public Amazon CA, so the runtime uses REDIS_CA_MODE=system
# (system trust store) instead of a bundled CA PEM.
resource "aws_secretsmanager_secret_version" "redis_auth" {
  count = var.enable_replication ? 1 : 0

  secret_id     = aws_secretsmanager_secret.redis_auth[0].id
  secret_string = jsonencode({ password = random_password.redis_auth[0].result })

  lifecycle {
    # Terraform writes only the initial token; the rotation Lambda (rotation.tf,
    # #159) owns subsequent AWSCURRENT versions, so do not revert secret_string.
    ignore_changes = [secret_string]
  }
}

# ------------------------------------------------------------------------------
# ElastiCache Redis - Replication Group (prod)
# ------------------------------------------------------------------------------

resource "aws_elasticache_replication_group" "ha" {
  count = var.enable_replication ? 1 : 0

  replication_group_id = "${var.name_prefix}-redis"
  description          = "Redis replication group for ${var.name_prefix}"
  engine               = "redis"
  engine_version       = var.engine_version
  node_type            = var.node_type
  apply_immediately    = var.apply_immediately
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

  # AUTH + in-transit encryption (#938) plus data-at-rest encryption under a
  # dedicated customer-managed CMK (#1059). The at-rest key is distinct from the
  # Secrets Manager CMK that protects the AUTH token secret; automated snapshots
  # of this replication group inherit kms_key_id automatically.
  at_rest_encryption_enabled = true
  transit_encryption_enabled = true
  kms_key_id                 = var.redis_at_rest_kms_key_arn
  auth_token                 = random_password.redis_auth[0].result

  # Order the runtime contract: the AWSCURRENT secret version (the value the
  # portal hydrates into REDIS_PASSWORD) must exist before ElastiCache starts
  # requiring the token. Without this edge Terraform could begin the
  # replication-group update — and publish the secret ARN to SSM/EC2 consumers
  # via redis_endpoint — while the secret-version write is still pending or
  # fails, leaving Redis demanding AUTH with no value to authenticate with.
  depends_on = [aws_secretsmanager_secret_version.redis_auth]

  tags = merge(var.tags, {
    Name   = "${var.name_prefix}-redis"
    Module = "redis"
  })

  lifecycle {
    # The AUTH token is rotated out-of-band by the rotation Lambda (rotation.tf,
    # #159) via the ElastiCache ROTATE strategy. Terraform bootstraps the
    # initial token from random_password.redis_auth; ignoring auth_token here
    # stops a later apply from reverting the live (rotated) token.
    ignore_changes = [auth_token]

    precondition {
      condition     = length(var.allowed_security_group_ids) > 0 || length(var.allowed_cidr_blocks) > 0
      error_message = "portal/redis: at least one of allowed_security_group_ids or allowed_cidr_blocks must be non-empty so the Redis security group has an ingress source."
    }
    precondition {
      condition     = var.secrets_kms_key_arn != ""
      error_message = "portal/redis: enable_replication requires secrets_kms_key_arn so the Redis AUTH token secret is encrypted by the portal CMK."
    }
    precondition {
      condition     = var.redis_at_rest_kms_key_arn != ""
      error_message = "portal/redis: enable_replication requires redis_at_rest_kms_key_arn so the replication group's data at rest is encrypted by a dedicated customer-managed CMK (#1059)."
    }
  }
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
