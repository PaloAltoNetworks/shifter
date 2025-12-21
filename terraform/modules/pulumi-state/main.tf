# ------------------------------------------------------------------------------
# Pulumi State Backend Infrastructure
# ------------------------------------------------------------------------------
# This module creates S3 bucket and DynamoDB table for Pulumi state management.
# S3 stores the state files, DynamoDB provides locking for concurrent operations.
# ------------------------------------------------------------------------------

locals {
  common_tags = merge(var.tags, {
    Module = "pulumi-state"
  })
}

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

# ------------------------------------------------------------------------------
# S3 Bucket for Pulumi State
# ------------------------------------------------------------------------------

resource "aws_s3_bucket" "pulumi_state" {
  bucket = "${var.name_prefix}-pulumi-state"

  # State is critical - do not allow accidental deletion
  force_destroy = false

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-pulumi-state"
  })
}

resource "aws_s3_bucket_versioning" "pulumi_state" {
  bucket = aws_s3_bucket.pulumi_state.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "pulumi_state" {
  bucket = aws_s3_bucket.pulumi_state.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = "alias/aws/s3"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "pulumi_state" {
  bucket = aws_s3_bucket.pulumi_state.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "pulumi_state" {
  bucket = aws_s3_bucket.pulumi_state.id

  rule {
    id     = "abort-incomplete-multipart"
    status = "Enabled"

    filter {} # Apply to all objects

    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }

  rule {
    id     = "noncurrent-version-management"
    status = "Enabled"

    filter {} # Apply to all objects

    noncurrent_version_transition {
      noncurrent_days = var.noncurrent_version_transition_days
      storage_class   = "GLACIER"
    }

    noncurrent_version_expiration {
      noncurrent_days = var.noncurrent_version_expiration_days
    }
  }
}

# ------------------------------------------------------------------------------
# KMS Key for Pulumi Secrets Encryption
# ------------------------------------------------------------------------------
# Pulumi encrypts sensitive config values before storing in state.
# Using a dedicated CMK provides:
# - Defense in depth (secrets encrypted even if S3 leaks)
# - CloudTrail audit trail for all encrypt/decrypt operations
# - Least privilege access control via key policy

resource "aws_kms_key" "pulumi_secrets" {
  description             = "Encrypts Pulumi stack secrets"
  deletion_window_in_days = 7
  enable_key_rotation     = true

  # Key policy: allow account root + provisioner role
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowAccountRoot"
        Effect = "Allow"
        Principal = {
          AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"
        }
        Action   = "kms:*"
        Resource = "*"
      }
    ]
  })

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-pulumi-secrets"
  })
}

resource "aws_kms_alias" "pulumi_secrets" {
  name          = "alias/${var.name_prefix}-pulumi-secrets"
  target_key_id = aws_kms_key.pulumi_secrets.key_id
}

# ------------------------------------------------------------------------------
# DynamoDB Table for Pulumi Locking
# ------------------------------------------------------------------------------

resource "aws_dynamodb_table" "pulumi_locks" {
  name         = "${var.name_prefix}-pulumi-locks"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID"

  attribute {
    name = "LockID"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled = true
  }

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-pulumi-locks"
  })
}
