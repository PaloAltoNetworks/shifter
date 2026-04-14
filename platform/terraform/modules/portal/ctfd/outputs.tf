output "instance_id" {
  description = "CTFd instance ID"
  value       = aws_instance.this.id
}

output "private_ip" {
  description = "CTFd private IP"
  value       = aws_instance.this.private_ip
}

output "elastic_ip" {
  description = "CTFd Elastic IP address"
  value       = aws_eip.this.public_ip
}

output "url" {
  description = "Public CTFd URL after DNS is in place"
  value       = "https://${var.domain}"
}

output "certbot_command" {
  description = "Run this on the instance after DNS resolves"
  value       = "sudo certbot --nginx -d ${var.domain}"
}

output "ssm_connect_command" {
  description = "SSM shell access to the instance"
  value       = "aws ssm start-session --target ${aws_instance.this.id} --region ${var.aws_region}"
}

output "ssh_command" {
  description = "Direct SSH command for the CTFd host"
  value       = "ssh ec2-user@${aws_eip.this.public_ip}"
}

output "ssh_key_name" {
  description = "EC2 key pair name configured for SSH access"
  value       = var.ssh_public_key != "" ? aws_key_pair.this[0].key_name : ""
}

output "security_group_id" {
  description = "Security group ID for the CTFd host"
  value       = aws_security_group.this.id
}
