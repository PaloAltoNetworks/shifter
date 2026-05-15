# S3 Module - User file storage
#
# Creates:
# - S3 bucket for user uploads (agents, etc.)
# - Block public access
#
# Note: No versioning, backup, or storage limits. Data is ephemeral.

locals {
  common_tags = merge(var.tags, {
    Module = "s3"
  })
}

# checkov:skip=CKV_AWS_21:Versioning intentionally disabled - ephemeral data, see #109
# checkov:skip=CKV_AWS_18:Access logging deferred to the unified logging strategy - see #310
# checkov:skip=CKV2_AWS_62:No S3 event consumer exists; creating an unused notification stream just to silence Checkov is an anti-pattern - see docs/architecture/s3-bucket-hardening-preflight.md. Revisit when a real consumer (Macie, SQS scanner, Lambda) is added.
# checkov:skip=CKV_AWS_144:Cross-region replication deferred - see #219
resource "aws_s3_bucket" "this" {
  bucket = var.bucket_name

  tags = merge(local.common_tags, {
    Name = var.bucket_name
  })
}

resource "aws_s3_bucket_versioning" "this" {
  bucket = aws_s3_bucket.this.id
  versioning_configuration {
    status = "Disabled"
  }
}

# SSE-KMS with bucket key enabled (CKV_AWS_145 / #218). bucket_key_enabled
# caches a per-bucket data key, dropping KMS API calls (and cost) by ~99% for
# repeated object reads/writes.
resource "aws_s3_bucket_server_side_encryption_configuration" "this" {
  bucket = aws_s3_bucket.this.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = var.kms_key_arn
    }
    bucket_key_enabled = true
  }
}
resource "aws_s3_bucket_public_access_block" "this" {
  bucket = aws_s3_bucket.this.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Enforce SSE-KMS with the supplied CMK on every PUT, and require TLS for
# every request. The default-encryption configuration above only applies when
# the caller omits the encryption headers — without this bucket policy a
# caller with `s3:PutObject` could still upload with `aws:kms` using a
# different key (or `AES256`) and bypass the CMK boundary. Combined with the
# bucket's CORS allowlist and the presigned-URL upload path used by the
# portal, the policy makes the CMK the only writable encryption mode.
#
# Existing-object backfill is out of scope: the portal user-uploads bucket
# is ephemeral per the module header. If a long-lived bucket later adopts
# this pattern, run S3 Batch Operations COPY-in-place to re-encrypt under
# the new CMK.
data "aws_iam_policy_document" "enforce_kms" {
  statement {
    sid     = "DenyNonTLSRequests"
    effect  = "Deny"
    actions = ["s3:*"]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    resources = [
      aws_s3_bucket.this.arn,
      "${aws_s3_bucket.this.arn}/*",
    ]
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }

  statement {
    sid     = "DenyUnencryptedPuts"
    effect  = "Deny"
    actions = ["s3:PutObject"]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    resources = ["${aws_s3_bucket.this.arn}/*"]
    condition {
      test     = "StringNotEquals"
      variable = "s3:x-amz-server-side-encryption"
      values   = ["aws:kms"]
    }
    condition {
      # `Null = true` matches the case where the header is absent at all,
      # not merely set to a non-`aws:kms` value.
      test     = "Null"
      variable = "s3:x-amz-server-side-encryption"
      values   = ["false"]
    }
  }

  statement {
    # When the caller explicitly names a KMS key on PutObject, it must be the
    # bucket's CMK. `StringNotEquals` (not `*IfExists`) is deliberate: in a
    # Deny statement, `IfExists` would also match when the header is absent,
    # which would deny normal presigned uploads that rely on the bucket's
    # default SSE-KMS configuration. Absent header → falls through to the
    # `aws_s3_bucket_server_side_encryption_configuration` default (our CMK).
    sid     = "DenyWrongKmsKeyOnPuts"
    effect  = "Deny"
    actions = ["s3:PutObject"]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    resources = ["${aws_s3_bucket.this.arn}/*"]
    condition {
      test     = "StringNotEquals"
      variable = "s3:x-amz-server-side-encryption-aws-kms-key-id"
      values   = [var.kms_key_arn]
    }
  }
}

resource "aws_s3_bucket_policy" "enforce_kms" {
  bucket = aws_s3_bucket.this.id
  policy = data.aws_iam_policy_document.enforce_kms.json
}

# CORS configuration for presigned URL uploads from browser
resource "aws_s3_bucket_cors_configuration" "this" {
  count  = length(var.cors_allowed_origins) > 0 ? 1 : 0
  bucket = aws_s3_bucket.this.id

  cors_rule {
    allowed_headers = ["*"]
    allowed_methods = ["PUT"]
    allowed_origins = var.cors_allowed_origins
    expose_headers  = ["ETag"]
    max_age_seconds = 3600
  }
}

# Lifecycle rule to clean up incomplete/orphaned uploads
resource "aws_s3_bucket_lifecycle_configuration" "this" {
  bucket = aws_s3_bucket.this.id

  rule {
    id     = "abort-incomplete-multipart"
    status = "Enabled"

    filter {}

    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }
}
