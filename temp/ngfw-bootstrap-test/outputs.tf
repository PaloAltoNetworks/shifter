output "instance_id" {
  description = "EC2 instance ID"
  value       = aws_instance.ngfw.id
}

output "management_public_ip" {
  description = "Management interface public IP (for SSH/HTTPS access)"
  value       = aws_eip.mgmt.public_ip
}

output "management_private_ip" {
  description = "Management interface private IP"
  value       = aws_network_interface.mgmt.private_ip
}

output "data_private_ip" {
  description = "Data interface private IP (ethernet1/1)"
  value       = aws_network_interface.data.private_ip
}

output "bootstrap_bucket" {
  description = "S3 bootstrap bucket name"
  value       = aws_s3_bucket.bootstrap.id
}

output "ssh_command" {
  description = "SSH command to connect to NGFW"
  value       = "ssh -i ${path.module}/ngfw-test-key.pem admin@${aws_eip.mgmt.public_ip}"
}

output "https_url" {
  description = "HTTPS URL for NGFW web UI"
  value       = "https://${aws_eip.mgmt.public_ip}"
}
