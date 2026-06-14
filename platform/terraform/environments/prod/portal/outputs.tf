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
# RDS
# ------------------------------------------------------------------------------

output "db_instance_id" {
  description = "DBInstanceIdentifier of the portal RDS instance (consumed by the post-apply pending-modifications check)"
  value       = module.rds.db_instance_id
}

output "guacamole_db_instance_id" {
  description = "DBInstanceIdentifier of the Guacamole RDS instance (consumed by the post-apply pending-modifications check)"
  value       = module.guacamole.db_instance_id
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

output "enable_autoscaling" {
  description = "Whether the portal EC2 tier is deployed as an Auto Scaling Group."
  value       = var.enable_autoscaling
}

output "ec2_instance_id" {
  description = "ID of the EC2 instance (empty if ASG mode)"
  value       = module.ec2.instance_id
}

output "ec2_private_ip" {
  description = "Private IP of the EC2 instance (empty if ASG mode)"
  value       = module.ec2.private_ip
}

output "asg_name" {
  description = "Auto Scaling Group name (empty if single instance mode)"
  value       = module.ec2.asg_name
}

output "asg_arn" {
  description = "Auto Scaling Group ARN (empty if single instance mode)"
  value       = module.ec2.asg_arn
}

output "launch_template_id" {
  description = "Launch template ID (empty if single instance mode)"
  value       = module.ec2.launch_template_id
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

output "alb_https_listener_arn" {
  description = "ARN of the ALB HTTPS listener"
  value       = module.alb.https_listener_arn
}

output "alb_security_group_id" {
  description = "Security group ID of the ALB"
  value       = module.alb.security_group_id
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

output "engine_ecs_cluster_arn" {
  description = "ARN of the engine provisioner ECS cluster"
  value       = module.engine_provisioner.ecs_cluster_arn
}

output "engine_ecs_cluster_name" {
  description = "Name of the engine provisioner ECS cluster"
  value       = module.engine_provisioner.ecs_cluster_name
}

output "engine_task_definition_arn" {
  description = "ARN of the engine provisioner ECS task definition"
  value       = module.engine_provisioner.task_definition_arn
}

output "engine_task_definition_family" {
  description = "Family of the engine provisioner ECS task definition"
  value       = module.engine_provisioner.task_definition_family
}

output "engine_ecs_security_group_id" {
  description = "ID of the engine provisioner ECS task security group"
  value       = module.engine_provisioner.ecs_security_group_id
}

output "engine_private_subnet_ids" {
  description = "List of private subnet IDs for ECS tasks"
  value       = module.engine_provisioner.private_subnet_ids
}

output "engine_ecs_execution_role_arn" {
  description = "ARN of the ECS execution role"
  value       = module.engine_provisioner.ecs_execution_role_arn
}

output "engine_ecs_task_role_arn" {
  description = "ARN of the ECS task role"
  value       = module.engine_provisioner.ecs_task_role_arn
}

# ------------------------------------------------------------------------------
# Guacamole
# ------------------------------------------------------------------------------

output "guacamole_target_group_arn" {
  description = "ARN of the Guacamole target group"
  value       = module.guacamole.target_group_arn
}

output "guacamole_json_auth_secret_arn" {
  description = "ARN of the Guacamole JSON auth secret (for Portal Django GUACAMOLE_JSON_AUTH_SECRET)"
  value       = module.guacamole.json_auth_secret_arn
}
