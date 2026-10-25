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

output "private_route_table_ids" {
  description = "IDs of the per-AZ private route tables, ordered by availability_zones."
  value       = module.vpc.private_route_table_ids
}

# ------------------------------------------------------------------------------
# Portal east-west inspection assertion contract (#932)
# ------------------------------------------------------------------------------
# Typed, non-secret topology consumed by the post-apply assertion
# (scripts/assert_portal_inspection). All per-AZ lists are ordered by
# availability_zones. A future staging environment or enforcement-mode change
# reuses the same assertion entrypoint with different topology data.

output "portal_inspection_assertion" {
  description = "Typed contract consumed by scripts/assert_portal_inspection to prove NFW route/endpoint wiring post-apply (#932)."
  value = {
    inspection_enabled       = module.vpc.inspection_enabled
    firewall_arn             = module.vpc.firewall_arn
    availability_zones       = module.vpc.availability_zones
    endpoint_ids_by_az       = module.vpc.firewall_endpoint_ids_by_az
    public_route_table_ids   = module.vpc.public_route_table_ids
    private_route_table_ids  = module.vpc.private_route_table_ids
    firewall_route_table_ids = module.vpc.firewall_route_table_ids
    public_subnet_cidrs      = module.vpc.public_subnet_cidrs
    private_subnet_cidrs     = module.vpc.private_subnet_cidrs
    firewall_subnet_cidrs    = module.vpc.firewall_subnet_cidrs
    nat_gateway_id           = module.vpc.nat_gateway_id
    nat_gateway_ids          = module.vpc.nat_gateway_ids
  }
}

# ------------------------------------------------------------------------------
# RDS
# ------------------------------------------------------------------------------

output "db_instance_id" {
  description = "DBInstanceIdentifier of the portal RDS instance (consumed by the post-apply pending-modifications check)"
  value       = module.rds.db_instance_id
}

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

output "db_resource_id" {
  description = "Resource ID of the RDS instance (for IAM DB authentication)"
  value       = module.rds.db_resource_id
}

# ------------------------------------------------------------------------------
# EC2 / Autoscaling
# ------------------------------------------------------------------------------

# ------------------------------------------------------------------------------
# ALB
# ------------------------------------------------------------------------------

output "domain_name" {
  description = "Public portal hostname served by the ALB"
  value       = var.domain_name
}

# ------------------------------------------------------------------------------
# App Secrets
# ------------------------------------------------------------------------------

output "app_secret_arn" {
  description = "ARN of the Secrets Manager secret containing Django app secrets"
  value       = aws_secretsmanager_secret.app.arn
}

# ------------------------------------------------------------------------------
# Cognito
# ------------------------------------------------------------------------------

output "cognito_user_pool_id" {
  description = "Cognito user pool ID"
  value       = module.cognito.user_pool_id
}

output "cognito_client_id" {
  description = "Cognito user pool client ID"
  value       = module.cognito.client_id
}

output "cognito_domain" {
  description = "Cognito hosted UI domain"
  value       = module.cognito.cognito_domain
}

output "cognito_issuer_url" {
  description = "OIDC issuer URL"
  value       = module.cognito.issuer_url
}

# ------------------------------------------------------------------------------
# VPC Peering
# ------------------------------------------------------------------------------

output "vpc_peering_connection_id" {
  description = "ID of the VPC peering connection to Range VPC"
  value       = aws_vpc_peering_connection.portal_to_range.id
}

# ------------------------------------------------------------------------------
# Redis
# ------------------------------------------------------------------------------

output "redis_endpoint" {
  description = "Redis primary endpoint"
  value       = module.redis.redis_endpoint
}

output "redis_port" {
  description = "Redis port"
  value       = module.redis.redis_port
}

# ------------------------------------------------------------------------------
# Engine Provisioner (ECS)
# ------------------------------------------------------------------------------

# ------------------------------------------------------------------------------
# Guacamole
# ------------------------------------------------------------------------------
