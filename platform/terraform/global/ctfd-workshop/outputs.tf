output "ctfd_instance_id" {
  description = "CTFd instance ID"
  value       = aws_instance.ctfd.id
}

output "ctfd_private_ip" {
  description = "CTFd private IP"
  value       = aws_instance.ctfd.private_ip
}

output "ctfd_elastic_ip" {
  description = "CTFd Elastic IP address"
  value       = aws_eip.ctfd.public_ip
}

output "ctfd_url" {
  description = "Public CTFd URL after DNS is in place"
  value       = "https://${var.domain}"
}

output "certbot_command" {
  description = "Run this on the instance after DNS resolves"
  value       = "sudo certbot --nginx -d ${var.domain}"
}

output "ssm_connect_command" {
  description = "SSM shell access to the instance"
  value       = "aws ssm start-session --target ${aws_instance.ctfd.id} --region ${var.aws_region}"
}
