# RDS Module - PostgreSQL database
#
# Creates:
# - DB subnet group
# - Security group for RDS
# - Secrets Manager secret for DB credentials
# - RDS PostgreSQL instance

# ------------------------------------------------------------------------------
# DB Subnet Group
# ------------------------------------------------------------------------------

resource "aws_db_subnet_group" "this" {
  name       = "${var.name_prefix}-db-subnet"
  subnet_ids = var.subnet_ids

  tags = merge(var.tags, {
    Name   = "${var.name_prefix}-db-subnet"
    Module = "rds"
  })
}

# ------------------------------------------------------------------------------
# Security Group for RDS
# ------------------------------------------------------------------------------

resource "aws_security_group" "this" {
  name        = "${var.name_prefix}-rds-sg"
  description = "Security group for RDS PostgreSQL"
  vpc_id      = var.vpc_id

  tags = merge(var.tags, {
    Name   = "${var.name_prefix}-rds-sg"
    Module = "rds"
  })
}

resource "aws_security_group_rule" "ingress_postgres" {
  count = length(var.allowed_cidr_blocks) > 0 ? 1 : 0

  type              = "ingress"
  from_port         = 5432
  to_port           = 5432
  protocol          = "tcp"
  cidr_blocks       = var.allowed_cidr_blocks
  security_group_id = aws_security_group.this.id
  description       = "PostgreSQL access (CIDR-based)"
}

resource "aws_security_group_rule" "ingress_postgres_sg" {
  count = length(var.allowed_security_group_ids)

  type                     = "ingress"
  from_port                = 5432
  to_port                  = 5432
  protocol                 = "tcp"
  source_security_group_id = var.allowed_security_group_ids[count.index]
  security_group_id        = aws_security_group.this.id
  description              = "PostgreSQL access (SG-based)"
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
# Secrets Manager - DB Credentials
# ------------------------------------------------------------------------------

resource "random_password" "db_password" {
  length           = 32
  special          = true
  override_special = "!#$%&*()-_=+[]{}<>:?"
}

resource "aws_secretsmanager_secret" "db_credentials" {
  name                    = "shifter-${var.name_prefix}-db-credentials"
  description             = "RDS PostgreSQL credentials"
  recovery_window_in_days = 0 # Immediate deletion, avoids naming conflicts on recreate
  kms_key_id              = var.secrets_kms_key_arn

  tags = merge(var.tags, {
    Name   = "shifter-${var.name_prefix}-db-credentials"
    Module = "rds"
  })
}

resource "aws_secretsmanager_secret_version" "db_credentials" {
  secret_id = aws_secretsmanager_secret.db_credentials.id
  secret_string = jsonencode({
    username = var.db_username
    password = random_password.db_password.result
    host     = aws_db_instance.this.address
    port     = aws_db_instance.this.port
    dbname   = var.db_name
    engine   = "postgresql"
  })
}

# ------------------------------------------------------------------------------
# RDS PostgreSQL Instance
# ------------------------------------------------------------------------------

resource "aws_db_instance" "this" {
  # checkov:skip=CKV_AWS_157:Multi-AZ controlled by var.multi_az; environments choose
  # checkov:skip=CKV_AWS_293:Deletion protection controlled by var.deletion_protection (dev false / prod true)
  identifier = "${var.name_prefix}-db"

  # Engine
  engine               = "postgres"
  engine_version       = var.engine_version
  instance_class       = var.instance_class
  parameter_group_name = aws_db_parameter_group.this.name
  ca_cert_identifier   = var.ca_cert_identifier

  # Storage
  allocated_storage     = var.allocated_storage
  max_allocated_storage = var.max_allocated_storage
  storage_type          = "gp3"
  storage_encrypted     = true
  kms_key_id            = aws_kms_key.rds.arn

  # Database
  db_name  = var.db_name
  username = var.db_username
  password = random_password.db_password.result
  port     = 5432

  # Network
  db_subnet_group_name   = aws_db_subnet_group.this.name
  vpc_security_group_ids = [aws_security_group.this.id]
  publicly_accessible    = false
  multi_az               = var.multi_az

  # Maintenance
  backup_retention_period    = var.backup_retention_days
  backup_window              = "03:00-04:00"
  maintenance_window         = "Mon:04:00-Mon:05:00"
  auto_minor_version_upgrade = true
  deletion_protection        = var.deletion_protection
  skip_final_snapshot        = var.skip_final_snapshot
  final_snapshot_identifier  = var.skip_final_snapshot ? null : "${var.name_prefix}-db-final"
  copy_tags_to_snapshot      = true

  # Enhanced monitoring (CKV_AWS_118) and Performance Insights with CMK
  # (CKV_AWS_354). 60-second OS metrics is the lowest non-zero interval that
  # doesn't materially affect cost on `db.t*g.*` / `db.m6*` classes.
  monitoring_interval                   = 60
  monitoring_role_arn                   = aws_iam_role.enhanced_monitoring.arn
  performance_insights_enabled          = true
  performance_insights_retention_period = 7
  performance_insights_kms_key_id       = aws_kms_key.rds.arn

  # IAM Database Authentication (for Lambda provisioner)
  iam_database_authentication_enabled = true

  # CloudWatch Log Exports
  enabled_cloudwatch_logs_exports = var.enable_log_exports ? ["postgresql", "upgrade"] : []

  # Whether class/storage/parameter changes apply during the deploy or wait
  # for the maintenance window. Set true in dev, false in prod.
  apply_immediately = var.apply_immediately

  lifecycle {
    precondition {
      condition     = length(var.allowed_security_group_ids) > 0 || length(var.allowed_cidr_blocks) > 0
      error_message = "portal/rds: at least one of allowed_security_group_ids or allowed_cidr_blocks must be non-empty so the RDS security group has an ingress source."
    }
  }

  tags = merge(var.tags, {
    Name   = "${var.name_prefix}-db"
    Module = "rds"
  })

  depends_on = [
    aws_cloudwatch_log_group.rds_postgresql,
    aws_cloudwatch_log_group.rds_upgrade,
  ]
}

# ------------------------------------------------------------------------------
# CloudWatch Log Groups for RDS
# RDS auto-creates these, but we define them for retention control
# ------------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "rds_postgresql" {
  count = var.enable_log_exports ? 1 : 0

  name              = "/aws/rds/instance/${var.name_prefix}-db/postgresql"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.cloudwatch_logs.arn

  tags = merge(var.tags, {
    Name   = "${var.name_prefix}-rds-postgresql-logs"
    Module = "rds"
  })
}

resource "aws_cloudwatch_log_group" "rds_upgrade" {
  count = var.enable_log_exports ? 1 : 0

  name              = "/aws/rds/instance/${var.name_prefix}-db/upgrade"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.cloudwatch_logs.arn

  tags = merge(var.tags, {
    Name   = "${var.name_prefix}-rds-upgrade-logs"
    Module = "rds"
  })
}
