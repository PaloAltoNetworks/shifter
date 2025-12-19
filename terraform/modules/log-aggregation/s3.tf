# Log Aggregation Module - S3 Bucket for Log Storage
#
# Creates:
# - S3 bucket for centralized log storage
# - Server-side encryption (SSE-S3)
# - Lifecycle policy (transition to IA, then expire)
# - Block public access
# - Bucket policy for Firehose access

locals {
  common_tags = merge(var.tags, {
    Module = "log-aggregation"
  })
}

# ------------------------------------------------------------------------------
# S3 Bucket for Logs
# ------------------------------------------------------------------------------

resource "aws_s3_bucket" "logs" {
  count  = var.enable_log_aggregation ? 1 : 0
  bucket = "${var.name_prefix}-logs-${var.environment}"

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-logs-${var.environment}"
  })
}

# Versioning disabled for logs (ephemeral data)
resource "aws_s3_bucket_versioning" "logs" {
  count  = var.enable_log_aggregation ? 1 : 0
  bucket = aws_s3_bucket.logs[0].id

  versioning_configuration {
    status = "Disabled"
  }
}

# Server-side encryption with S3-managed keys
resource "aws_s3_bucket_server_side_encryption_configuration" "logs" {
  count  = var.enable_log_aggregation ? 1 : 0
  bucket = aws_s3_bucket.logs[0].id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Block all public access
resource "aws_s3_bucket_public_access_block" "logs" {
  count  = var.enable_log_aggregation ? 1 : 0
  bucket = aws_s3_bucket.logs[0].id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Lifecycle policy: transition to IA after 30 days, expire after retention period
resource "aws_s3_bucket_lifecycle_configuration" "logs" {
  count  = var.enable_log_aggregation ? 1 : 0
  bucket = aws_s3_bucket.logs[0].id

  rule {
    id     = "log-lifecycle"
    status = "Enabled"

    filter {}

    transition {
      days          = 30
      storage_class = "STANDARD_IA"
    }

    expiration {
      days = var.log_retention_days
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }
}

# Bucket policy allowing Firehose and ALB to write logs
resource "aws_s3_bucket_policy" "logs" {
  count  = var.enable_log_aggregation ? 1 : 0
  bucket = aws_s3_bucket.logs[0].id

  # Depend on public access block to avoid race condition
  depends_on = [aws_s3_bucket_public_access_block.logs]

  policy = data.aws_iam_policy_document.logs[0].json
}

# Policy document for logs bucket - uses dynamic statements for conditional policies
data "aws_iam_policy_document" "logs" {
  count = var.enable_log_aggregation ? 1 : 0

  # Firehose write access (always enabled when log aggregation is on)
  statement {
    sid    = "AllowFirehoseWrite"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["firehose.amazonaws.com"]
    }

    actions = [
      "s3:AbortMultipartUpload",
      "s3:GetBucketLocation",
      "s3:GetObject",
      "s3:ListBucket",
      "s3:ListBucketMultipartUploads",
      "s3:PutObject"
    ]

    resources = [
      aws_s3_bucket.logs[0].arn,
      "${aws_s3_bucket.logs[0].arn}/*"
    ]

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }

  # ALB access logs - ELB service account (conditional)
  dynamic "statement" {
    for_each = var.enable_alb_access_logs ? [1] : []
    content {
      sid    = "AllowALBAccessLogs"
      effect = "Allow"

      principals {
        type        = "AWS"
        identifiers = [data.aws_elb_service_account.main.arn]
      }

      actions   = ["s3:PutObject"]
      resources = ["${aws_s3_bucket.logs[0].arn}/alb/*"]
    }
  }

  # ALB access logs - delivery.logs.amazonaws.com for new format (conditional)
  dynamic "statement" {
    for_each = var.enable_alb_access_logs ? [1] : []
    content {
      sid    = "AllowALBAccessLogsDelivery"
      effect = "Allow"

      principals {
        type        = "Service"
        identifiers = ["delivery.logs.amazonaws.com"]
      }

      actions   = ["s3:PutObject"]
      resources = ["${aws_s3_bucket.logs[0].arn}/alb/*"]

      condition {
        test     = "StringEquals"
        variable = "s3:x-amz-acl"
        values   = ["bucket-owner-full-control"]
      }
    }
  }

  # ALB access logs - GetBucketAcl permission (conditional)
  dynamic "statement" {
    for_each = var.enable_alb_access_logs ? [1] : []
    content {
      sid    = "AllowALBAccessLogsAcl"
      effect = "Allow"

      principals {
        type        = "Service"
        identifiers = ["delivery.logs.amazonaws.com"]
      }

      actions   = ["s3:GetBucketAcl"]
      resources = [aws_s3_bucket.logs[0].arn]
    }
  }
}

data "aws_caller_identity" "current" {}

# ELB service account for ALB access logs (region-specific)
data "aws_elb_service_account" "main" {}
