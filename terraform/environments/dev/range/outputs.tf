# Range environment outputs

output "vpc_id" {
  description = "ID of the range VPC"
  value       = module.vpc.vpc_id
}

output "vpc_cidr" {
  description = "CIDR block of the range VPC"
  value       = module.vpc.vpc_cidr
}

output "availability_zone" {
  description = "Primary availability zone used by the Range VPC"
  value       = module.vpc.availability_zone
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

# ------------------------------------------------------------------------------
# Pulumi State Backend
# ------------------------------------------------------------------------------

output "pulumi_state_bucket_name" {
  description = "Name of the Pulumi state S3 bucket"
  value       = var.enable_pulumi_provisioner ? module.pulumi_state[0].bucket_name : null
}

output "pulumi_state_bucket_arn" {
  description = "ARN of the Pulumi state S3 bucket"
  value       = var.enable_pulumi_provisioner ? module.pulumi_state[0].bucket_arn : null
}

output "pulumi_locks_table_name" {
  description = "Name of the Pulumi locks DynamoDB table"
  value       = var.enable_pulumi_provisioner ? module.pulumi_state[0].dynamodb_table_name : null
}

output "pulumi_locks_table_arn" {
  description = "ARN of the Pulumi locks DynamoDB table"
  value       = var.enable_pulumi_provisioner ? module.pulumi_state[0].dynamodb_table_arn : null
}
