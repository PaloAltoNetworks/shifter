# Portal environment outputs

# ------------------------------------------------------------------------------
# VPC
# ------------------------------------------------------------------------------

output "vpc_id" {
  description = "ID of the portal VPC"
  value       = module.vpc.vpc_id
}

output "vpc_cidr" {
  description = "CIDR block of the portal VPC"
  value       = module.vpc.vpc_cidr
}

output "public_subnet_ids" {
  description = "IDs of public subnets"
  value       = module.vpc.public_subnet_ids
}

output "private_subnet_ids" {
  description = "IDs of private subnets"
  value       = module.vpc.private_subnet_ids
}

output "availability_zones" {
  description = "Availability zones used"
  value       = module.vpc.availability_zones
}

# ------------------------------------------------------------------------------
# RDS
# ------------------------------------------------------------------------------

output "db_instance_endpoint" {
  description = "Endpoint of the RDS instance"
  value       = module.rds.db_instance_endpoint
}

output "db_instance_address" {
  description = "Address of the RDS instance"
  value       = module.rds.db_instance_address
}

output "db_credentials_secret_arn" {
  description = "ARN of the Secrets Manager secret containing DB credentials"
  value       = module.rds.db_credentials_secret_arn
}

output "db_security_group_id" {
  description = "ID of the RDS security group"
  value       = module.rds.db_security_group_id
}

# ------------------------------------------------------------------------------
# EC2
# ------------------------------------------------------------------------------

output "ec2_instance_id" {
  description = "ID of the EC2 instance"
  value       = module.ec2.instance_id
}

output "ec2_private_ip" {
  description = "Private IP of the EC2 instance"
  value       = module.ec2.private_ip
}

# ------------------------------------------------------------------------------
# ALB
# ------------------------------------------------------------------------------

output "alb_dns_name" {
  description = "DNS name of the ALB (create CNAME pointing to this)"
  value       = module.alb.alb_dns_name
}

output "acm_validation_records" {
  description = "DNS records to create for ACM certificate validation"
  value       = module.alb.acm_validation_records
}
