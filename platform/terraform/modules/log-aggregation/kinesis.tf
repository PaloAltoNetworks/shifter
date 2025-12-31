# Log Aggregation Module - Kinesis Firehose Delivery Stream
#
# Creates:
# - Kinesis Firehose delivery stream to S3
# - IAM role for Firehose with S3 write permissions
# - CloudWatch log group for Firehose errors

# ------------------------------------------------------------------------------
# CloudWatch Log Group for Firehose Errors
# ------------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "firehose_errors" {
  count = var.enable_log_aggregation ? 1 : 0

  name              = "/aws/firehose/${var.name_prefix}-logs-${var.environment}"
  retention_in_days = var.log_retention_days

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-firehose-errors-${var.environment}"
  })
}

resource "aws_cloudwatch_log_stream" "firehose_s3_delivery" {
  count = var.enable_log_aggregation ? 1 : 0

  name           = "S3Delivery"
  log_group_name = aws_cloudwatch_log_group.firehose_errors[0].name
}

# ------------------------------------------------------------------------------
# IAM Role for Firehose
# ------------------------------------------------------------------------------

resource "aws_iam_role" "firehose" {
  count = var.enable_log_aggregation ? 1 : 0

  name = "${var.name_prefix}-firehose-${var.environment}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "firehose.amazonaws.com"
        }
      }
    ]
  })

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-firehose-${var.environment}"
  })
}

resource "aws_iam_role_policy" "firehose_s3" {
  count = var.enable_log_aggregation ? 1 : 0

  name = "s3-write"
  role = aws_iam_role.firehose[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:AbortMultipartUpload",
          "s3:GetBucketLocation",
          "s3:GetObject",
          "s3:ListBucket",
          "s3:ListBucketMultipartUploads",
          "s3:PutObject"
        ]
        Resource = [
          aws_s3_bucket.logs[0].arn,
          "${aws_s3_bucket.logs[0].arn}/*"
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy" "firehose_logs" {
  count = var.enable_log_aggregation ? 1 : 0

  name = "cloudwatch-logs"
  role = aws_iam_role.firehose[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:PutLogEvents"
        ]
        Resource = "${aws_cloudwatch_log_group.firehose_errors[0].arn}:*"
      }
    ]
  })
}

# ------------------------------------------------------------------------------
# Kinesis Firehose Delivery Stream
# ------------------------------------------------------------------------------

resource "aws_kinesis_firehose_delivery_stream" "logs" {
  count = var.enable_log_aggregation ? 1 : 0

  name        = "${var.name_prefix}-logs-${var.environment}"
  destination = "extended_s3"

  extended_s3_configuration {
    role_arn   = aws_iam_role.firehose[0].arn
    bucket_arn = aws_s3_bucket.logs[0].arn

    # Partition logs by date for efficient querying
    prefix              = "logs/year=!{timestamp:yyyy}/month=!{timestamp:MM}/day=!{timestamp:dd}/"
    error_output_prefix = "errors/year=!{timestamp:yyyy}/month=!{timestamp:MM}/day=!{timestamp:dd}/!{firehose:error-output-type}/"

    buffering_size     = 5   # MB - minimum for cost efficiency
    buffering_interval = 300 # seconds (5 minutes)

    compression_format = "GZIP"

    cloudwatch_logging_options {
      enabled         = true
      log_group_name  = aws_cloudwatch_log_group.firehose_errors[0].name
      log_stream_name = aws_cloudwatch_log_stream.firehose_s3_delivery[0].name
    }
  }

  tags = merge(local.common_tags, {
    Name = "${var.name_prefix}-logs-${var.environment}"
  })
}

# ------------------------------------------------------------------------------
# WAF Firehose Delivery Stream
# WAF requires Firehose name to start with "aws-waf-logs-"
# ------------------------------------------------------------------------------

resource "aws_cloudwatch_log_stream" "firehose_waf_delivery" {
  count = var.enable_log_aggregation && var.enable_waf_logging ? 1 : 0

  name           = "WAFDelivery"
  log_group_name = aws_cloudwatch_log_group.firehose_errors[0].name
}

resource "aws_kinesis_firehose_delivery_stream" "waf" {
  count = var.enable_log_aggregation && var.enable_waf_logging ? 1 : 0

  # WAF requires this specific prefix
  name        = "aws-waf-logs-${var.name_prefix}-${var.environment}"
  destination = "extended_s3"

  extended_s3_configuration {
    role_arn   = aws_iam_role.firehose[0].arn
    bucket_arn = aws_s3_bucket.logs[0].arn

    # Partition WAF logs by date
    prefix              = "waf/year=!{timestamp:yyyy}/month=!{timestamp:MM}/day=!{timestamp:dd}/"
    error_output_prefix = "waf-errors/year=!{timestamp:yyyy}/month=!{timestamp:MM}/day=!{timestamp:dd}/!{firehose:error-output-type}/"

    buffering_size     = 5   # MB
    buffering_interval = 300 # seconds

    compression_format = "GZIP"

    cloudwatch_logging_options {
      enabled         = true
      log_group_name  = aws_cloudwatch_log_group.firehose_errors[0].name
      log_stream_name = aws_cloudwatch_log_stream.firehose_waf_delivery[0].name
    }
  }

  tags = merge(local.common_tags, {
    Name = "aws-waf-logs-${var.name_prefix}-${var.environment}"
  })
}
