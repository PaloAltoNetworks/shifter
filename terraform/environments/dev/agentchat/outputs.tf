output "instance_id" {
  description = "AgentChat EC2 instance ID"
  value       = module.ec2.instance_id
}

output "private_ip" {
  description = "AgentChat EC2 private IP"
  value       = module.ec2.private_ip
}

output "security_group_id" {
  description = "AgentChat EC2 security group ID"
  value       = module.ec2.security_group_id
}

