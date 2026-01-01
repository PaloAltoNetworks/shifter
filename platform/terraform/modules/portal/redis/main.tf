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
