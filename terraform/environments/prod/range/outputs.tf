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

output "dc_security_group_id" {
  description = "ID of the security group for Domain Controller instances"
  value       = module.vpc.dc_security_group_id
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
  value       = module.pulumi_state.bucket_name
}

output "pulumi_state_bucket_arn" {
  description = "ARN of the Pulumi state S3 bucket"
  value       = module.pulumi_state.bucket_arn
}

output "pulumi_locks_table_name" {
  description = "Name of the Pulumi locks DynamoDB table"
  value       = module.pulumi_state.dynamodb_table_name
}

output "pulumi_locks_table_arn" {
  description = "ARN of the Pulumi locks DynamoDB table"
  value       = module.pulumi_state.dynamodb_table_arn
}

output "pulumi_secrets_kms_key_arn" {
  description = "ARN of the KMS key for Pulumi secrets encryption"
  value       = module.pulumi_state.secrets_kms_key_arn
}

output "pulumi_secrets_kms_key_alias" {
  description = "Alias of the KMS key for Pulumi secrets encryption"
  value       = module.pulumi_state.secrets_kms_key_alias
}

# ------------------------------------------------------------------------------
# Range Instance IAM
# ------------------------------------------------------------------------------

output "range_instance_role_arn" {
  description = "ARN of the IAM role for range EC2 instances"
  value       = module.vpc.range_instance_role_arn
}

output "range_instance_profile_arn" {
  description = "ARN of the IAM instance profile for range EC2 instances"
  value       = module.vpc.range_instance_profile_arn
}

output "range_instance_profile_name" {
  description = "Name of the IAM instance profile for range EC2 instances"
  value       = module.vpc.range_instance_profile_name
}
