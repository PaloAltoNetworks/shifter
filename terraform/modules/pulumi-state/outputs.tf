# ------------------------------------------------------------------------------
# Outputs
# ------------------------------------------------------------------------------

output "bucket_name" {
  description = "Name of the Pulumi state S3 bucket"
  value       = aws_s3_bucket.pulumi_state.id
}

output "bucket_arn" {
  description = "ARN of the Pulumi state S3 bucket"
  value       = aws_s3_bucket.pulumi_state.arn
}

output "bucket_domain_name" {
  description = "Domain name of the Pulumi state S3 bucket"
  value       = aws_s3_bucket.pulumi_state.bucket_domain_name
}

output "dynamodb_table_name" {
  description = "Name of the Pulumi locks DynamoDB table"
  value       = aws_dynamodb_table.pulumi_locks.name
}

output "dynamodb_table_arn" {
  description = "ARN of the Pulumi locks DynamoDB table"
  value       = aws_dynamodb_table.pulumi_locks.arn
}

output "secrets_kms_key_arn" {
  description = "ARN of the KMS key for Pulumi secrets encryption"
  value       = aws_kms_key.pulumi_secrets.arn
}

output "secrets_kms_key_alias" {
  description = "Alias of the KMS key for Pulumi secrets encryption"
  value       = aws_kms_alias.pulumi_secrets.name
}
