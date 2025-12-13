output "instance_id" {
  description = "EC2 instance ID"
  value       = aws_instance.this.id
}

output "private_ip" {
  description = "Private IP address of the EC2 instance"
  value       = aws_instance.this.private_ip
}

output "security_group_id" {
  description = "Security group ID"
  value       = aws_security_group.this.id
}

output "iam_role_arn" {
  description = "IAM role ARN"
  value       = aws_iam_role.this.arn
}

output "bag_api_key_secret_arn" {
  description = "ARN of the Secrets Manager secret containing the BAG API key"
  value       = aws_secretsmanager_secret.bag_api_key.arn
}

