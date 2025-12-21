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

output "private_route_table_id" {
  description = "ID of the private route table (for NAT gateway access)"
  value       = module.vpc.private_route_table_id
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

output "db_resource_id" {
  description = "Resource ID of the RDS instance (for IAM DB authentication)"
  value       = module.rds.db_resource_id
}

# ------------------------------------------------------------------------------
# EC2 / Autoscaling
# ------------------------------------------------------------------------------

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
# Pulumi Provisioner
# ------------------------------------------------------------------------------

output "pulumi_ecs_cluster_arn" {
  description = "ARN of the Pulumi provisioner ECS cluster"
  value       = module.pulumi_provisioner.ecs_cluster_arn
}

output "pulumi_task_definition_arn" {
  description = "ARN of the Pulumi provisioner ECS task definition"
  value       = module.pulumi_provisioner.task_definition_arn
}

output "pulumi_ecs_security_group_id" {
  description = "ID of the Pulumi provisioner ECS security group"
  value       = module.pulumi_provisioner.ecs_security_group_id
}

output "pulumi_private_subnet_ids" {
  description = "Private subnet IDs for Pulumi provisioner ECS tasks"
  value       = module.pulumi_provisioner.private_subnet_ids
}

output "pulumi_ecs_execution_role_arn" {
  description = "ARN of the Pulumi provisioner ECS execution role"
  value       = module.pulumi_provisioner.ecs_execution_role_arn
}

output "pulumi_ecs_task_role_arn" {
  description = "ARN of the Pulumi provisioner ECS task role"
  value       = module.pulumi_provisioner.ecs_task_role_arn
}
