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

output "public_route_table_id" {
  description = "ID of the public route table (for user subnet associations)"
  value       = module.vpc.public_route_table_id
}

output "victim_security_group_id" {
  description = "ID of the security group for victim EC2 instances"
  value       = module.vpc.victim_security_group_id
}
