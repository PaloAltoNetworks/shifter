# ------------------------------------------------------------------------------
# ECS Outputs
# ------------------------------------------------------------------------------

output "ecs_cluster_arn" {
  description = "ARN of the ECS cluster"
  value       = aws_ecs_cluster.engine.arn
}

output "ecs_cluster_name" {
  description = "Name of the ECS cluster"
  value       = aws_ecs_cluster.engine.name
}

output "task_definition_arn" {
  description = "ARN of the ECS task definition"
  value       = aws_ecs_task_definition.engine_provisioner.arn
}

output "task_definition_family" {
  description = "Family of the ECS task definition"
  value       = aws_ecs_task_definition.engine_provisioner.family
}

# ------------------------------------------------------------------------------
# Security Group Outputs
# ------------------------------------------------------------------------------

output "ecs_security_group_id" {
  description = "ID of the ECS task security group"
  value       = aws_security_group.ecs_task.id
}

# ------------------------------------------------------------------------------
# IAM Outputs
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
# Secrets Manager Outputs
# ------------------------------------------------------------------------------

output "dc_domain_password_secret_arn" {
  description = "ARN of the Secrets Manager secret holding the prebaked DC Administrator password (created and managed out-of-band; resolved via data source)"
  value       = data.aws_secretsmanager_secret.dc_domain_password.arn
}

# ------------------------------------------------------------------------------
# CloudWatch Outputs
# ------------------------------------------------------------------------------

output "ecs_log_group_name" {
  description = "Name of the ECS CloudWatch log group"
  value       = aws_cloudwatch_log_group.ecs.name
}

output "log_group_names" {
  description = "List of all CloudWatch log group names (for log aggregation)"
  value = [
    aws_cloudwatch_log_group.ecs.name,
  ]
}

# ------------------------------------------------------------------------------
# Networking Outputs (pass-through for Portal)
# ------------------------------------------------------------------------------

output "private_subnet_ids" {
  description = "List of private subnet IDs for ECS tasks (pass-through)"
  value       = var.private_subnet_ids
}

# ------------------------------------------------------------------------------
# Alarm Outputs
# ------------------------------------------------------------------------------

output "range_launch_failures_sns_topic_arn" {
  description = "ARN of the SNS topic for range launch failure notifications"
  value       = var.enable_alarms ? aws_sns_topic.range_launch_failures[0].arn : null
}
