# Range VPC module outputs

output "vpc_id" {
  description = "ID of the VPC"
  value       = aws_vpc.this.id
}

output "vpc_cidr" {
  description = "CIDR block of the VPC"
  value       = aws_vpc.this.cidr_block
}

output "internet_gateway_id" {
  description = "ID of the internet gateway"
  value       = aws_internet_gateway.this.id
}

output "public_route_table_id" {
  description = "ID of the public route table (for user subnet associations)"
  value       = aws_route_table.public.id
}

output "victim_security_group_id" {
  description = "ID of the security group for victim EC2 instances"
  value       = aws_security_group.victim.id
}

output "kali_security_group_id" {
  description = "ID of the security group for Kali attack instances"
  value       = aws_security_group.kali.id
}
