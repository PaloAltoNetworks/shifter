# Portal-RDS Module - Customer-Managed KMS Key for storage + Performance Insights
#
# CMK for RDS storage encryption and Performance Insights (CKV_AWS_354).
# Distinct from the CloudWatch log groups CMK in kms.tf so the RDS service
# grant doesn't bleed into the log-group surface.

resource "aws_kms_key" "rds" {
  description             = "CMK for shifter portal-rds storage + Performance Insights (CKV_AWS_354)"
  enable_key_rotation     = true
  deletion_window_in_days = 30

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "EnableRootAccountAdmin"
        Effect    = "Allow"
        Principal = { AWS = "arn:aws:iam::${data.aws_caller_identity.kms_account.account_id}:root" }
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
            "aws:SourceAccount" = data.aws_caller_identity.kms_account.account_id
          }
        }
      },
    ]
  })

  tags = merge(var.tags, {
    Name   = "${var.name_prefix}-portal-rds-cmk"
    Module = "rds"
  })
}

resource "aws_kms_alias" "rds" {
  name          = "alias/${var.name_prefix}-portal-rds"
  target_key_id = aws_kms_key.rds.key_id
}

# Custom parameter group enabling Postgres statement logging so RDS Query
# Logging (CKV2_AWS_30) has a populated source. The values mirror CIS-style
# defaults and pass-through everything else from the default group.
resource "aws_db_parameter_group" "this" {
  name        = "${var.name_prefix}-postgres-pg"
  family      = "postgres${split(".", var.engine_version)[0]}"
  description = "Custom parameter group for ${var.name_prefix} portal RDS (query logging + force SSL)"

  parameter {
    name  = "log_statement"
    value = "all"
  }

  parameter {
    name  = "log_min_duration_statement"
    value = "0"
  }

  # Encryption in transit (CKV2_AWS_69) - require SSL/TLS for all client
  # connections. rds.force_ssl=1 needs `pending-reboot` apply method.
  parameter {
    name         = "rds.force_ssl"
    value        = "1"
    apply_method = "pending-reboot"
  }

  tags = merge(var.tags, {
    Name   = "${var.name_prefix}-postgres-pg"
    Module = "rds"
  })
}

# Enhanced monitoring role (CKV_AWS_118).
resource "aws_iam_role" "enhanced_monitoring" {
  name = "${var.name_prefix}-rds-enhanced-monitoring"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "monitoring.rds.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = merge(var.tags, {
    Module = "rds"
  })
}

resource "aws_iam_role_policy_attachment" "enhanced_monitoring" {
  role       = aws_iam_role.enhanced_monitoring.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonRDSEnhancedMonitoringRole"
}
