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

resource "aws_s3_bucket" "this" {
  bucket = var.bucket_name

  tags = merge(local.common_tags, {
    Name = var.bucket_name
  })
}

resource "aws_s3_bucket_public_access_block" "this" {
  bucket = aws_s3_bucket.this.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

