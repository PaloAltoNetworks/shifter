output "instance_id" {
  description = "WebServer1 instance ID"
  value       = aws_instance.webserver1.id
}

output "elastic_ip" {
  description = "WebServer1 Elastic IP address"
  value       = aws_eip.webserver1.public_ip
}

output "security_group_id" {
  description = "WebServer1 security group ID"
  value       = aws_security_group.webserver.id
}

output "ctfd_instance_id" {
  description = "CTFd instance ID"
  value       = aws_instance.ctfd.id
}

output "ctfd_elastic_ip" {
  description = "CTFd Elastic IP address"
  value       = aws_eip.ctfd.public_ip
}

# NGFW

output "ngfw_instance_id" {
  description = "NGFW instance ID"
  value       = aws_instance.ngfw.id
}

output "ngfw_mgmt_ip" {
  description = "NGFW management private IP"
  value       = aws_network_interface.ngfw_mgmt.private_ip
}

output "ngfw_mgmt_public_ip" {
  description = "NGFW management public IP (EIP)"
  value       = aws_eip.ngfw_mgmt.public_ip
}

output "ngfw_untrust_ip" {
  description = "NGFW untrust private IP"
  value       = aws_network_interface.ngfw_untrust.private_ip
}

output "ngfw_server_ip" {
  description = "NGFW server private IP"
  value       = aws_network_interface.ngfw_server.private_ip
}

output "ngfw_workstation_ip" {
  description = "NGFW workstation private IP"
  value       = aws_network_interface.ngfw_workstation.private_ip
}

output "ngfw_ssh_key_secret_arn" {
  description = "Secrets Manager ARN for NGFW SSH key"
  value       = aws_secretsmanager_secret.ngfw_ssh_key.arn
}

output "workstation_instance_id" {
  description = "Workstation instance ID"
  value       = aws_instance.workstation.id
}

output "workstation_private_ip" {
  description = "Workstation private IP"
  value       = aws_instance.workstation.private_ip
}
