# ------------------------------------------------------------------------------
# Guacamole Database (PostgreSQL)
# ------------------------------------------------------------------------------
# Creates a dedicated PostgreSQL database for Guacamole to store:
# - User authentication data
# - Connection definitions
# - Connection history and recordings

# ------------------------------------------------------------------------------
# DB Subnet Group
# ------------------------------------------------------------------------------

resource "aws_db_subnet_group" "guacamole" {
  name       = "${var.name_prefix}-guacamole-db-subnet"
  subnet_ids = var.private_subnet_ids

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-guacamole-db-subnet"
  })
}

# ------------------------------------------------------------------------------
# Secrets Manager - DB Credentials
# ------------------------------------------------------------------------------

resource "random_password" "db_password" {
  length           = 32
  special          = true
  override_special = "!#$%&*()-_=+[]{}<>:?"
}

# checkov:skip=CKV_AWS_149:AWS-managed keys sufficient for internal platform
resource "aws_secretsmanager_secret" "db_credentials" {
  name                    = "shifter-${var.name_prefix}-guacamole-db"
  description             = "Guacamole PostgreSQL database credentials"
  recovery_window_in_days = var.secrets_recovery_window_days

  tags = merge(local.common_tags, {
    Name = "shifter-${var.name_prefix}-guacamole-db"
  })
}

resource "aws_secretsmanager_secret_version" "db_credentials" {
  secret_id = aws_secretsmanager_secret.db_credentials.id
  secret_string = jsonencode({
    username = "guacamole_admin"
    password = random_password.db_password.result
    host     = aws_db_instance.guacamole.address
    port     = aws_db_instance.guacamole.port
    dbname   = "guacamole"
    engine   = "postgresql"
  })
}

# ------------------------------------------------------------------------------
# RDS PostgreSQL Instance
# ------------------------------------------------------------------------------

# checkov:skip=CKV_AWS_354:Performance insights enabled
# checkov:skip=CKV_AWS_353:Performance insights enabled
# checkov:skip=CKV_AWS_157:IAM auth not needed - Guacamole uses password auth
# checkov:skip=CKV_AWS_118:Enhanced monitoring deferred
# checkov:skip=CKV_AWS_293:CA certificate deferred
resource "aws_db_instance" "guacamole" {
  identifier = "${var.name_prefix}-guacamole-db"

  # Engine
  engine               = "postgres"
  engine_version       = var.db_engine_version
  instance_class       = var.db_instance_class
  parameter_group_name = "default.postgres${split(".", var.db_engine_version)[0]}"

  # Storage
  allocated_storage     = var.db_allocated_storage
  max_allocated_storage = var.db_max_allocated_storage
  storage_type          = "gp3"
  storage_encrypted     = true

  # Database
  db_name  = "guacamole"
  username = "guacamole_admin"
  password = random_password.db_password.result
  port     = 5432

  # Network
  db_subnet_group_name   = aws_db_subnet_group.guacamole.name
  vpc_security_group_ids = [aws_security_group.rds.id]
  publicly_accessible    = false
  multi_az               = var.db_multi_az

  # Maintenance
  backup_retention_period    = var.db_backup_retention_days
  backup_window              = "03:00-04:00"
  maintenance_window         = "Mon:04:00-Mon:05:00"
  auto_minor_version_upgrade = true
  deletion_protection        = var.db_deletion_protection
  skip_final_snapshot        = var.db_skip_final_snapshot
  final_snapshot_identifier  = var.db_skip_final_snapshot ? null : "${var.name_prefix}-guacamole-db-final"

  # Performance Insights (free tier for 7 days retention)
  performance_insights_enabled          = true
  performance_insights_retention_period = 7

  # CloudWatch Log Exports
  enabled_cloudwatch_logs_exports = ["postgresql", "upgrade"]

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-guacamole-db"
  })

  depends_on = [
    aws_cloudwatch_log_group.rds_postgresql,
    aws_cloudwatch_log_group.rds_upgrade,
  ]
}

# ------------------------------------------------------------------------------
# CloudWatch Log Groups for RDS
# ------------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "rds_postgresql" {
  name              = "/aws/rds/instance/${var.name_prefix}-guacamole-db/postgresql"
  retention_in_days = var.log_retention_days

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-guacamole-rds-postgresql-logs"
  })
}

resource "aws_cloudwatch_log_group" "rds_upgrade" {
  name              = "/aws/rds/instance/${var.name_prefix}-guacamole-db/upgrade"
  retention_in_days = var.log_retention_days

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-guacamole-rds-upgrade-logs"
  })
}
