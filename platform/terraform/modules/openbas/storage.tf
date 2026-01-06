# OpenBAS Storage
#
# Creates:
# - S3 bucket for OpenBAS file storage (scenarios, agent binaries, etc.)
# - Admin token secret

# ------------------------------------------------------------------------------
# S3 Bucket for OpenBAS Storage
# ------------------------------------------------------------------------------

# checkov:skip=CKV_AWS_145:SSE-S3 sufficient for MVP
# checkov:skip=CKV_AWS_144:Cross-region replication deferred
# checkov:skip=CKV2_AWS_62:Event notifications not needed
# checkov:skip=CKV_AWS_18:Access logging optional
resource "aws_s3_bucket" "openbas" {
  bucket = "${var.name_prefix}-openbas-${local.account_id}"

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-openbas-storage"
  })
}

resource "aws_s3_bucket_versioning" "openbas" {
  bucket = aws_s3_bucket.openbas.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "openbas" {
  bucket = aws_s3_bucket.openbas.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "openbas" {
  bucket = aws_s3_bucket.openbas.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "openbas" {
  bucket = aws_s3_bucket.openbas.id

  rule {
    id     = "cleanup-old-versions"
    status = "Enabled"

    noncurrent_version_expiration {
      noncurrent_days = 30
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

# ------------------------------------------------------------------------------
# Admin API Token
# ------------------------------------------------------------------------------

resource "random_password" "admin_token" {
  length  = 64
  special = false
}

# checkov:skip=CKV_AWS_149:AWS-managed keys sufficient for MVP
resource "aws_secretsmanager_secret" "admin_token" {
  name                    = "shifter/${var.name_prefix}-openbas-admin-token"
  description             = "OpenBAS admin API token"
  recovery_window_in_days = 0

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-openbas-admin-token"
  })
}

resource "aws_secretsmanager_secret_version" "admin_token" {
  secret_id = aws_secretsmanager_secret.admin_token.id
  secret_string = jsonencode({
    token = random_password.admin_token.result
  })
}
