# Range environment outputs

output "vpc_id" {
  description = "ID of the range VPC"
  value       = module.vpc.vpc_id
}

output "vpc_cidr" {
  description = "CIDR block of the range VPC"
  value       = module.vpc.vpc_cidr
}

output "internet_gateway_id" {
  description = "ID of the internet gateway"
  value       = module.vpc.internet_gateway_id
}

output "private_route_table_id" {
  description = "ID of the private route table (for user subnet associations)"
  value       = module.vpc.private_route_table_id
}

# DEPRECATED: Use private_route_table_id instead
output "public_route_table_id" {
  description = "DEPRECATED: Use private_route_table_id. Kept for backward compatibility."
  value       = module.vpc.public_route_table_id
}

output "victim_security_group_id" {
  description = "ID of the security group for victim EC2 instances"
  value       = module.vpc.victim_security_group_id
}

output "kali_security_group_id" {
  description = "ID of the security group for Kali attack instances"
  value       = module.vpc.kali_security_group_id
}

output "nat_gateway_id" {
  description = "ID of the NAT Gateway"
  value       = module.vpc.nat_gateway_id
}

output "firewall_arn" {
  description = "ARN of the Network Firewall (null if disabled)"
  value       = module.vpc.firewall_arn
}
