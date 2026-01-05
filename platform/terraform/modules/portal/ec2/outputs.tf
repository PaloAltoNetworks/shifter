output "instance_id" {
  description = "EC2 instance ID (empty string if ASG mode)"
  value       = var.enable_autoscaling ? "" : aws_instance.this[0].id
}

output "private_ip" {
  description = "Private IP address of the EC2 instance (empty string if ASG mode)"
  value       = var.enable_autoscaling ? "" : aws_instance.this[0].private_ip
}

output "security_group_id" {
  description = "Security group ID"
  value       = aws_security_group.this.id
}

output "iam_role_arn" {
  description = "IAM role ARN"
  value       = aws_iam_role.this.arn
}

output "asg_name" {
  description = "Auto Scaling Group name (empty string if single instance mode)"
  value       = var.enable_autoscaling ? aws_autoscaling_group.this[0].name : ""
}

output "asg_arn" {
  description = "Auto Scaling Group ARN (empty string if single instance mode)"
  value       = var.enable_autoscaling ? aws_autoscaling_group.this[0].arn : ""
}

output "launch_template_id" {
  description = "Launch template ID (empty string if single instance mode)"
  value       = var.enable_autoscaling ? aws_launch_template.this[0].id : ""
}

output "log_group_name" {
  description = "Name of the CloudWatch log group for portal containers"
  value       = aws_cloudwatch_log_group.portal.name
}

output "lifecycle_hook_name" {
  description = "Name of the ASG lifecycle hook (empty if not enabled)"
  value       = var.enable_autoscaling && var.ssm_document_name != "" ? aws_autoscaling_lifecycle_hook.launch[0].name : ""
}
