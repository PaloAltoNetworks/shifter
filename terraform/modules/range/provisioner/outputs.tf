# Provisioner Module Outputs

output "lambda_role_arn" {
  description = "ARN of the Lambda execution role"
  value       = aws_iam_role.lambda.arn
}

output "lambda_role_name" {
  description = "Name of the Lambda execution role"
  value       = aws_iam_role.lambda.name
}

output "lambda_security_group_id" {
  description = "Security group ID for Lambda functions"
  value       = aws_security_group.lambda.id
}

# Lambda Function ARNs (for Step Functions)
output "create_subnet_lambda_arn" {
  description = "ARN of the create_subnet Lambda function"
  value       = aws_lambda_function.create_subnet.arn
}

output "create_victim_lambda_arn" {
  description = "ARN of the create_victim Lambda function"
  value       = aws_lambda_function.create_victim.arn
}

output "create_kali_lambda_arn" {
  description = "ARN of the create_kali Lambda function"
  value       = aws_lambda_function.create_kali.arn
}

output "cleanup_lambda_arn" {
  description = "ARN of the cleanup Lambda function"
  value       = aws_lambda_function.cleanup.arn
}

output "find_stale_ranges_lambda_arn" {
  description = "ARN of the find_stale_ranges Lambda function"
  value       = aws_lambda_function.find_stale_ranges.arn
}

# Lambda Function Names (for logging/monitoring)
output "lambda_function_names" {
  description = "Names of all Lambda functions"
  value = {
    create_subnet     = aws_lambda_function.create_subnet.function_name
    create_victim     = aws_lambda_function.create_victim.function_name
    create_kali       = aws_lambda_function.create_kali.function_name
    cleanup           = aws_lambda_function.cleanup.function_name
    find_stale_ranges = aws_lambda_function.find_stale_ranges.function_name
  }
}

# Step Functions State Machine ARNs
output "provision_range_state_machine_arn" {
  description = "ARN of the provision range state machine"
  value       = aws_sfn_state_machine.provision_range.arn
}

output "teardown_range_state_machine_arn" {
  description = "ARN of the teardown range state machine"
  value       = aws_sfn_state_machine.teardown_range.arn
}

output "cleanup_stale_ranges_state_machine_arn" {
  description = "ARN of the cleanup stale ranges state machine"
  value       = aws_sfn_state_machine.cleanup_stale_ranges.arn
}

output "step_functions_role_arn" {
  description = "ARN of the Step Functions execution role"
  value       = aws_iam_role.step_functions.arn
}

output "range_instance_role_arn" {
  description = "ARN of the IAM role for range EC2 instances (for iam:PassRole)"
  value       = aws_iam_role.range_instance.arn
}

output "range_instance_profile_arn" {
  description = "ARN of the IAM instance profile for range EC2 instances"
  value       = aws_iam_instance_profile.range_instance.arn
}

output "range_instance_profile_name" {
  description = "Name of the IAM instance profile for range EC2 instances"
  value       = aws_iam_instance_profile.range_instance.name
}

# Monitoring
output "alerts_sns_topic_arn" {
  description = "ARN of the SNS topic for provisioner alerts (null if alarms disabled)"
  value       = var.enable_alarms ? aws_sns_topic.alerts[0].arn : null
}

# Log Groups (for log aggregation)
output "log_group_names" {
  description = "Names of all CloudWatch log groups"
  value = [
    aws_cloudwatch_log_group.create_subnet.name,
    aws_cloudwatch_log_group.create_victim.name,
    aws_cloudwatch_log_group.create_kali.name,
    aws_cloudwatch_log_group.mark_ready.name,
    aws_cloudwatch_log_group.verify_agent.name,
    aws_cloudwatch_log_group.cleanup.name,
    aws_cloudwatch_log_group.find_stale_ranges.name,
    aws_cloudwatch_log_group.step_functions.name,
  ]
}
