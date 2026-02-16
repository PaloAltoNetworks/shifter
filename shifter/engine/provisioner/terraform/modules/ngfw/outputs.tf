output "ec2_instance_id" {
  description = "EC2 instance ID"
  value       = aws_instance.ngfw.id
}

output "management_ip" {
  description = "Management ENI private IP"
  value       = aws_network_interface.mgmt.private_ip
}

output "dataplane_ip" {
  description = "Data plane ENI private IP"
  value       = aws_network_interface.data.private_ip
}

output "data_eni_id" {
  description = "Data ENI ID (for route table associations)"
  value       = aws_network_interface.data.id
}

output "ssh_key_secret_arn" {
  description = "ARN of the SSH key in Secrets Manager"
  value       = aws_secretsmanager_secret.ssh_key.arn
}
