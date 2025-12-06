# Pass through module outputs

output "vpc_id" {
  description = "ID of the portal VPC"
  value       = module.portal.vpc_id
}

output "vpc_cidr" {
  description = "CIDR block of the portal VPC"
  value       = module.portal.vpc_cidr
}

output "public_subnet_ids" {
  description = "IDs of public subnets"
  value       = module.portal.public_subnet_ids
}

output "private_subnet_ids" {
  description = "IDs of private subnets (for RDS, ECS)"
  value       = module.portal.private_subnet_ids
}

output "availability_zones" {
  description = "Availability zones used"
  value       = module.portal.availability_zones
}
