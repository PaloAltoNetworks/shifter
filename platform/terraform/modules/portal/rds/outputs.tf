# RDS module outputs

output "db_instance_id" {
  description = "ID of the RDS instance"
  value       = aws_db_instance.this.id
}

output "db_instance_address" {
  description = "Address of the RDS instance"
  value       = aws_db_instance.this.address
}

output "db_instance_endpoint" {
  description = "Endpoint of the RDS instance"
  value       = aws_db_instance.this.endpoint
}

output "db_instance_port" {
  description = "Port of the RDS instance"
  value       = aws_db_instance.this.port
}

output "db_name" {
  description = "Name of the database"
  value       = aws_db_instance.this.db_name
}

output "db_username" {
  description = "Master username"
  value       = aws_db_instance.this.username
  sensitive   = true
}

output "db_security_group_id" {
  description = "ID of the RDS security group"
  value       = aws_security_group.this.id
}

output "db_credentials_secret_arn" {
  description = "ARN of the Secrets Manager secret containing DB credentials"
  value       = aws_secretsmanager_secret.db_credentials.arn
}

output "db_credentials_secret_name" {
  description = "Name of the Secrets Manager secret containing DB credentials"
  value       = aws_secretsmanager_secret.db_credentials.name
}

output "db_resource_id" {
  description = "Resource ID of the RDS instance (for IAM DB authentication)"
  value       = aws_db_instance.this.resource_id
}

# ------------------------------------------------------------------------------
# Log Exports
# ------------------------------------------------------------------------------

output "log_group_names" {
  description = "Names of the CloudWatch log groups for RDS logs"
  value = var.enable_log_exports ? [
    aws_cloudwatch_log_group.rds_postgresql[0].name,
    aws_cloudwatch_log_group.rds_upgrade[0].name,
  ] : []
}
