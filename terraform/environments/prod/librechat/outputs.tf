# LibreChat Environment Outputs

output "instance_id" {
  description = "EC2 instance ID"
  value       = module.librechat.instance_id
}

output "private_ip" {
  description = "Private IP address of the EC2 instance"
  value       = module.librechat.private_ip
}

output "subnet_id" {
  description = "LibreChat subnet ID"
  value       = module.librechat.subnet_id
}

output "security_group_id" {
  description = "Security group ID"
  value       = module.librechat.security_group_id
}

output "secrets_arn" {
  description = "ARN of the Secrets Manager secret containing LibreChat secrets"
  value       = module.librechat.secrets_arn
}

