# OpenBAS Module Outputs

# ------------------------------------------------------------------------------
# ECS
# ------------------------------------------------------------------------------

output "ecs_cluster_id" {
  description = "ID of the ECS cluster"
  value       = aws_ecs_cluster.openbas.id
}

output "ecs_cluster_name" {
  description = "Name of the ECS cluster"
  value       = aws_ecs_cluster.openbas.name
}

output "ecs_cluster_arn" {
  description = "ARN of the ECS cluster"
  value       = aws_ecs_cluster.openbas.arn
}

output "ecs_service_name" {
  description = "Name of the ECS service"
  value       = aws_ecs_service.openbas.name
}

output "ecs_service_id" {
  description = "ID of the ECS service"
  value       = aws_ecs_service.openbas.id
}

output "task_definition_arn" {
  description = "ARN of the ECS task definition"
  value       = aws_ecs_task_definition.openbas.arn
}

# ------------------------------------------------------------------------------
# Networking
# ------------------------------------------------------------------------------

output "subnet_ids" {
  description = "IDs of the OpenBAS subnets"
  value       = aws_subnet.openbas[*].id
}

output "subnet_cidrs" {
  description = "CIDR blocks of the OpenBAS subnets"
  value       = aws_subnet.openbas[*].cidr_block
}

output "ecs_security_group_id" {
  description = "ID of the ECS task security group"
  value       = aws_security_group.ecs.id
}

output "rds_security_group_id" {
  description = "ID of the RDS security group"
  value       = aws_security_group.rds.id
}

# ------------------------------------------------------------------------------
# Target Group (for Portal ALB)
# ------------------------------------------------------------------------------

output "target_group_arn" {
  description = "ARN of the target group (for Portal ALB listener rule)"
  value       = aws_lb_target_group.openbas.arn
}

output "target_group_name" {
  description = "Name of the target group"
  value       = aws_lb_target_group.openbas.name
}

# ------------------------------------------------------------------------------
# Database
# ------------------------------------------------------------------------------

output "db_instance_id" {
  description = "ID of the RDS instance"
  value       = aws_db_instance.openbas.id
}

output "db_instance_arn" {
  description = "ARN of the RDS instance"
  value       = aws_db_instance.openbas.arn
}

output "db_endpoint" {
  description = "Connection endpoint for the RDS instance"
  value       = aws_db_instance.openbas.endpoint
}

output "db_address" {
  description = "Address of the RDS instance"
  value       = aws_db_instance.openbas.address
}

output "db_port" {
  description = "Port of the RDS instance"
  value       = aws_db_instance.openbas.port
}

output "db_name" {
  description = "Name of the database"
  value       = aws_db_instance.openbas.db_name
}

# ------------------------------------------------------------------------------
# Secrets
# ------------------------------------------------------------------------------

output "db_credentials_secret_arn" {
  description = "ARN of the Secrets Manager secret for DB credentials"
  value       = aws_secretsmanager_secret.db_credentials.arn
}

output "admin_token_secret_arn" {
  description = "ARN of the Secrets Manager secret for admin API token"
  value       = aws_secretsmanager_secret.admin_token.arn
}

# ------------------------------------------------------------------------------
# Storage
# ------------------------------------------------------------------------------

output "storage_bucket_id" {
  description = "ID of the S3 storage bucket"
  value       = aws_s3_bucket.openbas.id
}

output "storage_bucket_arn" {
  description = "ARN of the S3 storage bucket"
  value       = aws_s3_bucket.openbas.arn
}

# ------------------------------------------------------------------------------
# API Endpoint
# ------------------------------------------------------------------------------

output "api_endpoint" {
  description = "Base URL for OpenBAS API"
  value       = var.base_url
}

# ------------------------------------------------------------------------------
# IAM
# ------------------------------------------------------------------------------

output "ecs_execution_role_arn" {
  description = "ARN of the ECS execution role"
  value       = aws_iam_role.ecs_execution.arn
}

output "ecs_task_role_arn" {
  description = "ARN of the ECS task role"
  value       = aws_iam_role.ecs_task.arn
}

# ------------------------------------------------------------------------------
# Monitoring
# ------------------------------------------------------------------------------

output "alerts_sns_topic_arn" {
  description = "ARN of the SNS topic for OpenBAS alerts"
  value       = aws_sns_topic.openbas_alerts.arn
}
