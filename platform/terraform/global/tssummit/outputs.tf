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
