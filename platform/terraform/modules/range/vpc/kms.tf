# Range-VPC Module - Customer-Managed KMS Key
#
# Shared CMK for CloudWatch log groups (flow logs, firewall logs) AND
# Network Firewall encryption configuration (CKV_AWS_158, CKV_AWS_345,
# CKV_AWS_346). Reuses existing data sources declared elsewhere in the
# module (iam.tf for aws_caller_identity, ssm-endpoints.tf for aws_region).

resource "aws_kms_key" "range_vpc" {
  description             = "CMK for shifter range-vpc CW logs and Network Firewall encryption (CKV_AWS_158, CKV_AWS_345)"
  enable_key_rotation     = true
  deletion_window_in_days = 30

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "EnableRootAccountAdmin"
        Effect    = "Allow"
        Principal = { AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root" }
        Action    = "kms:*"
        Resource  = "*"
      },
      {
        Sid       = "AllowCloudWatchLogs"
        Effect    = "Allow"
        Principal = { Service = "logs.${data.aws_region.current.name}.amazonaws.com" }
        Action = [
          "kms:Encrypt*",
          "kms:Decrypt*",
          "kms:ReEncrypt*",
          "kms:GenerateDataKey*",
          "kms:DescribeKey",
        ]
        Resource = "*"
        Condition = {
          ArnLike = {
            "kms:EncryptionContext:aws:logs:arn" = "arn:aws:logs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:*"
          }
        }
      },
      {
        # Network Firewall calls KMS via the firewall and rule-group control
        # planes. Scope to the account; the firewall resources themselves
        # are pinned by `kms_key_id` references on each consumer.
        Sid       = "AllowNetworkFirewallService"
        Effect    = "Allow"
        Principal = { Service = "network-firewall.amazonaws.com" }
        Action = [
          "kms:Decrypt",
          "kms:GenerateDataKey",
          "kms:DescribeKey",
        ]
        Resource = "*"
        Condition = {
          StringEquals = {
            "aws:SourceAccount" = data.aws_caller_identity.current.account_id
          }
        }
      },
    ]
  })

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-range-vpc-cmk"
  })
}

resource "aws_kms_alias" "range_vpc" {
  name          = "alias/${var.name_prefix}-range-vpc"
  target_key_id = aws_kms_key.range_vpc.key_id
}
