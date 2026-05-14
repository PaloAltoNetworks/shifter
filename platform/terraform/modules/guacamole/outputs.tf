# ------------------------------------------------------------------------------
# ECS Outputs
# ------------------------------------------------------------------------------

output "ecs_cluster_arn" {
  description = "ARN of the Guacamole ECS cluster"
  value       = aws_ecs_cluster.guacamole.arn
}

output "ecs_cluster_name" {
  description = "Name of the Guacamole ECS cluster"
  value       = aws_ecs_cluster.guacamole.name
}

output "guacd_service_name" {
  description = "Name of the guacd ECS service"
  value       = aws_ecs_service.guacd.name
}

output "guacamole_client_service_name" {
  description = "Name of the guacamole-client ECS service"
  value       = aws_ecs_service.guacamole_client.name
}

# ------------------------------------------------------------------------------
# Target Group Output
# ------------------------------------------------------------------------------

output "target_group_arn" {
  description = "ARN of the Guacamole target group"
  value       = aws_lb_target_group.guacamole.arn
}

# ------------------------------------------------------------------------------
# Security Group Outputs
# ------------------------------------------------------------------------------

output "guacamole_client_security_group_id" {
  description = "ID of the guacamole-client security group"
  value       = aws_security_group.guacamole_client.id
}

output "guacd_security_group_id" {
  description = "ID of the guacd security group"
  value       = aws_security_group.guacd.id
}

output "rds_security_group_id" {
  description = "ID of the RDS security group"
  value       = aws_security_group.rds.id
}

# ------------------------------------------------------------------------------
# Database Outputs
# ------------------------------------------------------------------------------

output "db_instance_id" {
  description = "DBInstanceIdentifier of the Guacamole RDS instance"
  # `.identifier`, not `.id`: under AWS provider v5+ `aws_db_instance.id` is the
  # DbiResourceId (db-XXXX), but consumers (the post-apply RDS check) need the
  # DBInstanceIdentifier name.
  value = aws_db_instance.guacamole.identifier
}

output "db_instance_address" {
  description = "Address of the Guacamole RDS instance"
  value       = aws_db_instance.guacamole.address
}

output "db_instance_port" {
  description = "Port of the Guacamole RDS instance"
  value       = aws_db_instance.guacamole.port
}

output "db_credentials_secret_arn" {
  description = "ARN of the Secrets Manager secret containing DB credentials"
  value       = aws_secretsmanager_secret.db_credentials.arn
}

output "json_auth_secret_arn" {
  description = "ARN of the Secrets Manager secret containing JSON auth key for Portal RDP integration"
  value       = aws_secretsmanager_secret.json_auth.arn
}

# ------------------------------------------------------------------------------
# Service Discovery Outputs
# ------------------------------------------------------------------------------

output "service_discovery_namespace_id" {
  description = "ID of the service discovery namespace"
  value       = aws_service_discovery_private_dns_namespace.guacamole.id
}

output "service_discovery_namespace_name" {
  description = "Name of the service discovery namespace"
  value       = aws_service_discovery_private_dns_namespace.guacamole.name
}

output "guacd_service_discovery_hostname" {
  description = "DNS hostname for guacd service discovery"
  value       = "guacd.${aws_service_discovery_private_dns_namespace.guacamole.name}"
}

output "guacamole_client_service_discovery_hostname" {
  description = "DNS hostname for guacamole-client service discovery"
  value       = "guacamole-client.${aws_service_discovery_private_dns_namespace.guacamole.name}"
}

output "guacamole_client_internal_url" {
  description = "Internal URL for guacamole-client API calls (for Django backend)"
  value       = "http://guacamole-client.${aws_service_discovery_private_dns_namespace.guacamole.name}:8080/guacamole"
}

# ------------------------------------------------------------------------------
# CloudWatch Log Group Outputs
# ------------------------------------------------------------------------------

output "guacd_log_group_name" {
  description = "Name of the guacd CloudWatch log group"
  value       = aws_cloudwatch_log_group.guacd.name
}

output "guacamole_client_log_group_name" {
  description = "Name of the guacamole-client CloudWatch log group"
  value       = aws_cloudwatch_log_group.guacamole_client.name
}

output "log_group_names" {
  description = "List of all CloudWatch log group names (for log aggregation)"
  value = [
    aws_cloudwatch_log_group.guacd.name,
    aws_cloudwatch_log_group.guacamole_client.name,
    aws_cloudwatch_log_group.rds_postgresql.name,
    aws_cloudwatch_log_group.rds_upgrade.name,
  ]
}

# ------------------------------------------------------------------------------
# IAM Outputs
# ------------------------------------------------------------------------------

output "ecs_execution_role_arn" {
  description = "ARN of the ECS execution role"
  value       = aws_iam_role.ecs_execution.arn
}

output "guacamole_client_task_role_arn" {
  description = "ARN of the guacamole-client task role"
  value       = aws_iam_role.guacamole_client_task.arn
}

output "guacd_task_role_arn" {
  description = "ARN of the guacd task role"
  value       = aws_iam_role.guacd_task.arn
}
