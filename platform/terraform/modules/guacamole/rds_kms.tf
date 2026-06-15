# Guacamole Module - RDS storage + PI CMK + enhanced monitoring role
#
# Distinct from the CloudWatch Logs CMK in kms.tf. RDS service principals
# need encrypt/decrypt/CreateGrant on this key.

resource "aws_kms_key" "rds" {
  description             = "CMK for shifter guacamole RDS storage + Performance Insights (CKV_AWS_354)"
  enable_key_rotation     = true
  deletion_window_in_days = 30

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "EnableRootAccountAdmin"
        Effect    = "Allow"
        Principal = { AWS = "arn:aws:iam::${local.account_id}:root" }
        Action    = "kms:*"
        Resource  = "*"
      },
      {
        Sid       = "AllowRDSService"
        Effect    = "Allow"
        Principal = { Service = "rds.amazonaws.com" }
        Action = [
          "kms:Encrypt",
          "kms:Decrypt",
          "kms:ReEncrypt*",
          "kms:GenerateDataKey*",
          "kms:DescribeKey",
          "kms:CreateGrant",
        ]
        Resource = "*"
        Condition = {
          StringEquals = {
            "aws:SourceAccount" = local.account_id
          }
        }
      },
    ]
  })

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-guacamole-rds-cmk"
  })
}

resource "aws_kms_alias" "rds" {
  name          = "alias/${var.name_prefix}-guacamole-rds"
  target_key_id = aws_kms_key.rds.key_id
}

# Custom Postgres parameter group enabling query logging (CKV2_AWS_30).
resource "aws_db_parameter_group" "guacamole" {
  name        = "${var.name_prefix}-guacamole-postgres-pg"
  family      = "postgres${split(".", var.db_engine_version)[0]}"
  description = "Guacamole RDS parameter group (query logging + force SSL)"

  parameter {
    name  = "log_statement"
    value = "all"
  }

  parameter {
    name  = "log_min_duration_statement"
    value = "0"
  }

  # Encryption in transit (CKV2_AWS_69).
  parameter {
    name         = "rds.force_ssl"
    value        = "1"
    apply_method = "pending-reboot"
  }

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-guacamole-postgres-pg"
  })
}

# Enhanced monitoring role (CKV_AWS_118).
resource "aws_iam_role" "rds_enhanced_monitoring" {
  name = "${var.name_prefix}-guacamole-rds-enhanced-monitoring"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "monitoring.rds.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = local.common_tags
}

resource "aws_iam_role_policy_attachment" "rds_enhanced_monitoring" {
  role       = aws_iam_role.rds_enhanced_monitoring.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonRDSEnhancedMonitoringRole"
}
