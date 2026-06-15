# Log Aggregation Module - S3 Buckets for Log Storage
#
# Creates:
# - S3 bucket for centralized log storage
# - Dedicated S3 bucket for ALB access logs
# - Server-side encryption
# - Lifecycle policy (transition to IA, then expire)
# - Block public access
# - Bucket policies for Firehose and ALB log delivery

locals {
  common_tags = merge(var.tags, {
    Module = "log-aggregation"
  })
}

# ------------------------------------------------------------------------------
# S3 Bucket for Logs
# ------------------------------------------------------------------------------

resource "aws_s3_bucket" "logs" {
  count = var.enable_log_aggregation ? 1 : 0
  # Account-id suffix keeps the name globally unique (S3 namespace is shared
  # across all AWS accounts) without sacrificing per-account determinism.
  bucket = "${var.name_prefix}-logs-${var.environment}-${data.aws_caller_identity.current.account_id}"

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

# Server-side encryption with the log-aggregation customer-managed CMK
# (Checkov CKV_AWS_145). `bucket_key_enabled = true` reduces per-object KMS
# calls so SSE-KMS does not balloon Firehose costs.
resource "aws_s3_bucket_server_side_encryption_configuration" "logs" {
  count  = var.enable_log_aggregation ? 1 : 0
  bucket = aws_s3_bucket.logs[0].id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.log_aggregation[0].arn
    }
    bucket_key_enabled = true
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

# ------------------------------------------------------------------------------
# S3 Bucket for ALB Access Logs
# ------------------------------------------------------------------------------

resource "aws_s3_bucket" "alb_access_logs" {
  # checkov:skip=CKV_AWS_145:ALB access log delivery supports SSE-S3 only; central Firehose logs stay SSE-KMS.
  count = var.enable_alb_access_logs ? 1 : 0
  # ALB access-log buckets must be in the same region as the load balancer.
  # Account-id suffix keeps the name deterministic and globally unique.
  bucket = "${var.name_prefix}-alb-logs-${var.environment}-${data.aws_caller_identity.current.account_id}"

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-alb-logs-${var.environment}"
  })
}

# Versioning disabled for append-only ALB log objects.
resource "aws_s3_bucket_versioning" "alb_access_logs" {
  count  = var.enable_alb_access_logs ? 1 : 0
  bucket = aws_s3_bucket.alb_access_logs[0].id

  versioning_configuration {
    status = "Disabled"
  }
}

# ALB access logs only support Amazon S3-managed keys (SSE-S3), not SSE-KMS.
resource "aws_s3_bucket_server_side_encryption_configuration" "alb_access_logs" {
  count  = var.enable_alb_access_logs ? 1 : 0
  bucket = aws_s3_bucket.alb_access_logs[0].id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "alb_access_logs" {
  count  = var.enable_alb_access_logs ? 1 : 0
  bucket = aws_s3_bucket.alb_access_logs[0].id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "alb_access_logs" {
  count  = var.enable_alb_access_logs ? 1 : 0
  bucket = aws_s3_bucket.alb_access_logs[0].id

  rule {
    id     = "alb-log-lifecycle"
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

# Bucket policy allowing Firehose to write centralized logs
resource "aws_s3_bucket_policy" "logs" {
  count  = var.enable_log_aggregation ? 1 : 0
  bucket = aws_s3_bucket.logs[0].id

  # Depend on public access block to avoid race condition
  depends_on = [aws_s3_bucket_public_access_block.logs]

  policy = data.aws_iam_policy_document.logs[0].json
}

# Bucket policy allowing ELB log delivery to write ALB access logs
resource "aws_s3_bucket_policy" "alb_access_logs" {
  count  = var.enable_alb_access_logs ? 1 : 0
  bucket = aws_s3_bucket.alb_access_logs[0].id

  depends_on = [aws_s3_bucket_public_access_block.alb_access_logs]

  policy = data.aws_iam_policy_document.alb_access_logs[0].json
}

# Policy document for the central logs bucket
data "aws_iam_policy_document" "logs" {
  count = var.enable_log_aggregation ? 1 : 0

  # Deny non-HTTPS requests
  statement {
    sid    = "DenyInsecureTransport"
    effect = "Deny"

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    actions = ["s3:*"]

    resources = [
      aws_s3_bucket.logs[0].arn,
      "${aws_s3_bucket.logs[0].arn}/*"
    ]

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }

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
}

# Policy document for the ALB access logs bucket
data "aws_iam_policy_document" "alb_access_logs" {
  count = var.enable_alb_access_logs ? 1 : 0

  # Deny non-HTTPS requests
  statement {
    sid    = "DenyInsecureTransport"
    effect = "Deny"

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    actions = ["s3:*"]

    resources = [
      aws_s3_bucket.alb_access_logs[0].arn,
      "${aws_s3_bucket.alb_access_logs[0].arn}/*"
    ]

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }

  # ALB access logs - modern ELB log delivery service principal.
  statement {
    sid    = "AllowALBLogDeliveryWrite"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["logdelivery.elasticloadbalancing.amazonaws.com"]
    }

    actions = ["s3:PutObject"]
    resources = [
      "${aws_s3_bucket.alb_access_logs[0].arn}/alb/${var.name_prefix}/AWSLogs/${data.aws_caller_identity.current.account_id}/*"
    ]
  }

  statement {
    sid    = "AllowALBLogDeliveryAclCheck"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["logdelivery.elasticloadbalancing.amazonaws.com"]
    }

    actions   = ["s3:GetBucketAcl"]
    resources = [aws_s3_bucket.alb_access_logs[0].arn]
  }
}

data "aws_caller_identity" "current" {}
