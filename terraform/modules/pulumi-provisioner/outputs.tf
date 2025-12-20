# ------------------------------------------------------------------------------
# ECS Outputs
# ------------------------------------------------------------------------------

output "ecs_cluster_arn" {
  description = "ARN of the ECS cluster"
  value       = aws_ecs_cluster.pulumi.arn
}

output "ecs_cluster_name" {
  description = "Name of the ECS cluster"
  value       = aws_ecs_cluster.pulumi.name
}

output "task_definition_arn" {
  description = "ARN of the ECS task definition"
  value       = aws_ecs_task_definition.pulumi_provisioner.arn
}

output "task_definition_family" {
  description = "Family of the ECS task definition"
  value       = aws_ecs_task_definition.pulumi_provisioner.family
}

# ------------------------------------------------------------------------------
# Step Functions Outputs
# ------------------------------------------------------------------------------

output "provision_state_machine_arn" {
  description = "ARN of the provision range Step Functions state machine"
  value       = aws_sfn_state_machine.provision_range_pulumi.arn
}

output "provision_state_machine_name" {
  description = "Name of the provision range Step Functions state machine"
  value       = aws_sfn_state_machine.provision_range_pulumi.name
}

output "destroy_state_machine_arn" {
  description = "ARN of the destroy range Step Functions state machine"
  value       = aws_sfn_state_machine.destroy_range_pulumi.arn
}

output "destroy_state_machine_name" {
  description = "Name of the destroy range Step Functions state machine"
  value       = aws_sfn_state_machine.destroy_range_pulumi.name
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

output "step_functions_role_arn" {
  description = "ARN of the Step Functions role"
  value       = aws_iam_role.step_functions.arn
}

# ------------------------------------------------------------------------------
# CloudWatch Outputs
# ------------------------------------------------------------------------------

output "ecs_log_group_name" {
  description = "Name of the ECS CloudWatch log group"
  value       = aws_cloudwatch_log_group.ecs.name
}

output "sfn_log_group_name" {
  description = "Name of the Step Functions CloudWatch log group"
  value       = aws_cloudwatch_log_group.sfn.name
}

output "log_group_names" {
  description = "List of all CloudWatch log group names (for log aggregation)"
  value = [
    aws_cloudwatch_log_group.ecs.name,
    aws_cloudwatch_log_group.sfn.name,
  ]
}
