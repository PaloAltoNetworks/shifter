output "instance_id" {
  description = "EC2 instance ID"
  value       = aws_spot_instance_request.dev_box.spot_instance_id
}

output "spot_request_id" {
  description = "Spot instance request ID"
  value       = aws_spot_instance_request.dev_box.id
}

output "private_ip" {
  description = "Private IP address"
  value       = aws_spot_instance_request.dev_box.private_ip
}

output "public_ip" {
  description = "Public IP address (if in public subnet)"
  value       = aws_spot_instance_request.dev_box.public_ip
}

output "ssm_connect_command" {
  description = "Command to connect via SSM Session Manager"
  value       = "aws ssm start-session --target ${aws_spot_instance_request.dev_box.spot_instance_id}"
}

output "fleet_manager_url" {
  description = "URL for SSM Fleet Manager RDP access"
  value       = "https://us-east-2.console.aws.amazon.com/systems-manager/fleet-manager/managed-nodes/${aws_spot_instance_request.dev_box.spot_instance_id}/connect?region=us-east-2"
}

output "admin_password_secret_arn" {
  description = "ARN of the Secrets Manager secret containing the admin password"
  value       = aws_secretsmanager_secret.admin_password.arn
}

output "admin_password_console_url" {
  description = "URL to retrieve admin password from Secrets Manager console"
  value       = "https://us-east-2.console.aws.amazon.com/secretsmanager/secret?name=shifter-dev-box-admin-password&region=us-east-2"
}
