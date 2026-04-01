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

output "ngfw_untrust_public_ip" {
  description = "NGFW untrust public IP (EIP)"
  value       = aws_eip.ngfw_untrust.public_ip
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

output "windows_server_instance_id" {
  description = "Windows Server instance ID"
  value       = aws_instance.windows_server.id
}

output "windows_desktop_instance_id" {
  description = "Windows Desktop instance ID"
  value       = aws_instance.windows_desktop.id
}

output "webserver_instance_id" {
  description = "Webserver instance ID"
  value       = aws_instance.webserver.id
}

output "ai_app_instance_id" {
  description = "AI App instance ID"
  value       = aws_instance.ai_app.id
}

output "ai_app_public_ip" {
  description = "AI App public IP (EIP)"
  value       = aws_eip.ai_app.public_ip
}

output "ai_app_private_ip" {
  description = "AI App private IP"
  value       = aws_instance.ai_app.private_ip
}
