# ------------------------------------------------------------------------------
# Outputs
# ------------------------------------------------------------------------------

output "bucket_name" {
  description = "Name of the engine state S3 bucket"
  value       = aws_s3_bucket.engine_state.id
}

output "bucket_arn" {
  description = "ARN of the engine state S3 bucket"
  value       = aws_s3_bucket.engine_state.arn
}

output "bucket_domain_name" {
  description = "Domain name of the engine state S3 bucket"
  value       = aws_s3_bucket.engine_state.bucket_domain_name
}

output "dynamodb_table_name" {
  description = "Name of the engine locks DynamoDB table"
  value       = aws_dynamodb_table.engine_locks.name
}

output "dynamodb_table_arn" {
  description = "ARN of the engine locks DynamoDB table"
  value       = aws_dynamodb_table.engine_locks.arn
}

output "secrets_kms_key_arn" {
  description = "ARN of the KMS key for engine secrets encryption"
  value       = aws_kms_key.engine_secrets.arn
}

output "secrets_kms_key_alias" {
  description = "Alias of the KMS key for engine secrets encryption"
  value       = aws_kms_alias.engine_secrets.name
}
