data "aws_caller_identity" "current" {}

resource "aws_kms_key" "cluster" {
  description             = "EKS secrets and control-plane logs for ${var.cluster_name}"
  enable_key_rotation     = true
  deletion_window_in_days = 30

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "EnableAccountAdministration"
        Effect    = "Allow"
        Principal = { AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root" }
        Action    = "kms:*"
        Resource  = "*"
      },
      {
        Sid       = "AllowCloudWatchLogs"
        Effect    = "Allow"
        Principal = { Service = "logs.${var.aws_region}.amazonaws.com" }
        Action = [
          "kms:Decrypt",
          "kms:Encrypt",
          "kms:GenerateDataKey*",
          "kms:ReEncrypt*",
        ]
        Resource = "*"
        Condition = {
          ArnLike = {
            "kms:EncryptionContext:aws:logs:arn" = [
              "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/eks/${var.cluster_name}/*",
              "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/vpc/${var.cluster_name}/*",
              "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:aws-waf-logs-${var.cluster_name}*",
            ]
          }
        }
      },
    ]
  })

  tags = merge(var.tags, {
    Name = "${var.cluster_name}-cluster"
  })
}

resource "aws_kms_alias" "cluster" {
  name          = "alias/${var.cluster_name}-cluster"
  target_key_id = aws_kms_key.cluster.key_id
}

resource "aws_kms_key" "secrets" {
  description             = "Secrets Manager payloads for ${var.cluster_name}"
  enable_key_rotation     = true
  deletion_window_in_days = 30

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "EnableAccountAdministration"
        Effect    = "Allow"
        Principal = { AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root" }
        Action    = "kms:*"
        Resource  = "*"
      },
      {
        Sid       = "AllowAccountUseThroughSecretsManager"
        Effect    = "Allow"
        Principal = { AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root" }
        Action = [
          "kms:Decrypt",
          "kms:DescribeKey",
          "kms:Encrypt",
          "kms:GenerateDataKey*",
          "kms:ReEncrypt*",
          "kms:CreateGrant",
        ]
        Resource = "*"
        Condition = {
          StringEquals = {
            "kms:CallerAccount" = data.aws_caller_identity.current.account_id
            "kms:ViaService"    = "secretsmanager.${var.aws_region}.amazonaws.com"
          }
          StringLike = {
            "kms:EncryptionContext:SecretARN" = "arn:aws:secretsmanager:${var.aws_region}:${data.aws_caller_identity.current.account_id}:secret:shifter/${var.environment}/eks/*"
          }
        }
      },
    ]
  })

  tags = merge(var.tags, {
    Name = "${var.cluster_name}-secrets"
  })
}

resource "aws_kms_alias" "secrets" {
  name          = "alias/${var.cluster_name}-secrets"
  target_key_id = aws_kms_key.secrets.key_id
}

resource "aws_secretsmanager_secret" "platform" {
  for_each = var.secret_names

  name                    = "shifter/${var.environment}/eks/${each.value}"
  description             = "Out-of-band populated secret container for ${var.cluster_name}"
  kms_key_id              = aws_kms_key.secrets.arn
  recovery_window_in_days = 30

  tags = merge(var.tags, {
    Name = "${var.cluster_name}-${replace(each.value, "/", "-")}"
  })
}
