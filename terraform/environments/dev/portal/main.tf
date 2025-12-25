terraform {
  required_version = ">= 1.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

locals {
  name_prefix = "${var.environment}-portal"
}

# ------------------------------------------------------------------------------
# Remote State - Foundation (ECR)
# ------------------------------------------------------------------------------

data "terraform_remote_state" "foundation" {
  backend = "s3"
  config = {
    bucket = "shifter-dev-infra-e3462f0c-c5b5-4b47-836b-efe3f657858c"
    key    = "shifter/dev/terraform.tfstate"
    region = "us-east-2"
  }
}

# ------------------------------------------------------------------------------
# Remote State - Range VPC
# ------------------------------------------------------------------------------

data "terraform_remote_state" "range" {
  backend = "s3"
  config = {
    bucket = "shifter-dev-infra-e3462f0c-c5b5-4b47-836b-efe3f657858c"
    key    = "dev/range/terraform.tfstate"
    region = "us-east-2"
  }
}

# ------------------------------------------------------------------------------
# VPC
# ------------------------------------------------------------------------------

module "vpc" {
  source = "../../../modules/portal/vpc"

  name_prefix        = local.name_prefix
  vpc_cidr           = var.vpc_cidr
  az_count           = var.az_count
  enable_nat_gateway = var.enable_nat_gateway
  tags               = var.tags

  # Phase 5: VPC Flow Logs
  enable_flow_logs   = var.enable_vpc_flow_logs
  log_retention_days = var.log_retention_days
}

# ------------------------------------------------------------------------------
# RDS PostgreSQL
# ------------------------------------------------------------------------------

module "rds" {
  source = "../../../modules/portal/rds"

  name_prefix         = local.name_prefix
  vpc_id              = module.vpc.vpc_id
  subnet_ids          = module.vpc.private_subnet_ids
  allowed_cidr_blocks = [module.vpc.vpc_cidr]

  db_name               = var.db_name
  db_username           = var.db_username
  engine_version        = var.db_engine_version
  instance_class        = var.db_instance_class
  allocated_storage     = var.db_allocated_storage
  max_allocated_storage = var.db_max_allocated_storage
  multi_az              = var.db_multi_az
  backup_retention_days = var.db_backup_retention_days
  deletion_protection   = var.db_deletion_protection
  skip_final_snapshot   = var.db_skip_final_snapshot

  # Phase 5: RDS Log Exports
  enable_log_exports = var.enable_rds_log_exports
  log_retention_days = var.log_retention_days

  tags = var.tags
}

# ------------------------------------------------------------------------------
# ALB (created first, target attached after EC2)
# ------------------------------------------------------------------------------

module "alb" {
  source = "../../../modules/portal/alb"

  name_prefix       = local.name_prefix
  vpc_id            = module.vpc.vpc_id
  public_subnet_ids = module.vpc.public_subnet_ids
  domain_name       = var.domain_name
  app_port          = var.app_port
  health_check_path = var.health_check_path
  enable_stickiness = var.enable_autoscaling

  # Phase 5: ALB Access Logs and WAF Logging
  enable_access_logs      = var.enable_alb_access_logs
  logs_bucket_name        = var.enable_alb_access_logs ? module.log_aggregation.logs_bucket_name : ""
  enable_waf_logging      = var.enable_waf_logging
  waf_log_destination_arn = var.enable_waf_logging ? module.log_aggregation.waf_firehose_arn : ""

  tags = var.tags
}

# ------------------------------------------------------------------------------
# Redis (for Django Channels in ASG mode)
# ------------------------------------------------------------------------------

module "redis" {
  source = "../../../modules/portal/redis"

  name_prefix         = local.name_prefix
  vpc_id              = module.vpc.vpc_id
  subnet_ids          = module.vpc.private_subnet_ids
  allowed_cidr_blocks = [module.vpc.vpc_cidr]
  node_type           = var.redis_node_type
  engine_version      = var.redis_engine_version

  tags = var.tags
}

# ------------------------------------------------------------------------------
# Cognito
# ------------------------------------------------------------------------------

module "cognito" {
  source = "../../../modules/portal/cognito"

  name_prefix           = local.name_prefix
  environment           = var.environment
  aws_region            = var.aws_region
  log_retention_days    = var.log_retention_days
  cognito_domain_prefix = var.cognito_domain_prefix
  callback_urls         = ["https://${var.domain_name}/oidc/callback/"]
  logout_urls           = ["https://${var.domain_name}/"]
  allowed_email_domains = var.allowed_email_domains
  allowed_emails        = var.allowed_emails
  deletion_protection   = false

  tags = var.tags
}

# ------------------------------------------------------------------------------
# EC2
# ------------------------------------------------------------------------------

module "ec2" {
  source = "../../../modules/portal/ec2"

  aws_region            = var.aws_region
  name_prefix           = local.name_prefix
  vpc_id                = module.vpc.vpc_id
  subnet_id             = module.vpc.private_subnet_ids[0]
  alb_security_group_id = module.alb.security_group_id
  instance_type         = var.ec2_instance_type
  ecr_repository_arn    = data.terraform_remote_state.foundation.outputs.portal_ecr_arn
  ecr_repository_url    = data.terraform_remote_state.foundation.outputs.portal_ecr_url
  secret_arns = [
    module.rds.db_credentials_secret_arn,
    aws_secretsmanager_secret.app.arn,
    module.cognito.cognito_secret_arn,
  ]
  s3_bucket_arn    = module.s3.bucket_arn
  app_port         = var.app_port
  root_volume_size = var.ec2_root_volume_size

  # ECS permissions for Pulumi provisioner
  ecs_cluster_arn            = module.pulumi_provisioner.ecs_cluster_arn
  ecs_task_definition_family = module.pulumi_provisioner.task_definition_family
  ecs_task_role_arn          = module.pulumi_provisioner.ecs_task_role_arn
  ecs_execution_role_arn     = module.pulumi_provisioner.ecs_execution_role_arn

  # Autoscaling configuration
  enable_autoscaling   = var.enable_autoscaling
  subnet_ids           = module.vpc.private_subnet_ids
  target_group_arn     = module.alb.target_group_arn
  asg_min_size         = var.asg_min_size
  asg_max_size         = var.asg_max_size
  asg_desired_capacity = var.asg_desired_capacity
  redis_endpoint       = var.enable_autoscaling ? module.redis.redis_endpoint : ""
  scale_up_threshold   = var.scale_up_threshold
  scale_down_threshold = var.scale_down_threshold
  log_retention_days   = var.log_retention_days

  tags = var.tags
}

# ------------------------------------------------------------------------------
# ALB Target Attachment (single instance mode only - ASG attaches automatically)
# ------------------------------------------------------------------------------

resource "aws_lb_target_group_attachment" "portal" {
  count = var.enable_autoscaling ? 0 : 1

  target_group_arn = module.alb.target_group_arn
  target_id        = module.ec2.instance_id
  port             = var.app_port
}

# ------------------------------------------------------------------------------
# S3 User Storage
# ------------------------------------------------------------------------------

module "s3" {
  source = "../../../modules/portal/s3"

  bucket_name          = var.user_storage_bucket
  cors_allowed_origins = ["https://${var.domain_name}"]
  tags                 = var.tags
}

# ------------------------------------------------------------------------------
# App Secret (Django secret key)
# ------------------------------------------------------------------------------

resource "random_password" "django_secret_key" {
  length  = 50
  special = true
}

# checkov:skip=CKV_AWS_149:Deferred for MVP. AWS-managed keys sufficient for low-usage internal MVP. See #213
resource "aws_secretsmanager_secret" "app" {
  name                    = "shifter-${local.name_prefix}-app"
  description             = "Django application secrets"
  recovery_window_in_days = 0

  tags = merge(var.tags, {
    Name = "shifter-${local.name_prefix}-app"
  })
}

resource "aws_secretsmanager_secret_version" "app" {
  secret_id = aws_secretsmanager_secret.app.id
  secret_string = jsonencode({
    django_secret_key = random_password.django_secret_key.result
  })
}

# ------------------------------------------------------------------------------
# VPC Peering: Portal <-> Range
# Enables SSH connectivity from Portal to Range instances for Terminal UI
# ------------------------------------------------------------------------------

resource "aws_vpc_peering_connection" "portal_to_range" {
  vpc_id      = module.vpc.vpc_id
  peer_vpc_id = data.terraform_remote_state.range.outputs.vpc_id
  auto_accept = true # Same account, same region

  tags = merge(var.tags, {
    Name = "${local.name_prefix}-to-range-peering"
  })
}

# Route from Portal private subnets to Range VPC via peering
resource "aws_route" "portal_to_range" {
  route_table_id            = module.vpc.private_route_table_id
  destination_cidr_block    = data.terraform_remote_state.range.outputs.vpc_cidr
  vpc_peering_connection_id = aws_vpc_peering_connection.portal_to_range.id
}

# Route from Range private subnets to Portal VPC via peering
resource "aws_route" "range_to_portal" {
  route_table_id            = data.terraform_remote_state.range.outputs.private_route_table_id
  destination_cidr_block    = module.vpc.vpc_cidr
  vpc_peering_connection_id = aws_vpc_peering_connection.portal_to_range.id
}

# Note: SSH rules from Portal to Kali/Victim are defined in the range VPC module
# (terraform/modules/range/vpc/main.tf) using the portal_vpc_cidr variable.
# Do not duplicate them here.

# ------------------------------------------------------------------------------
# Pulumi Provisioner (ECS Fargate)
# Note: Defined before log_aggregation so its log groups can be included
# ------------------------------------------------------------------------------

module "pulumi_provisioner" {
  source = "../../../modules/pulumi-provisioner"

  name_prefix        = local.name_prefix
  environment        = var.environment
  tags               = var.tags
  log_retention_days = var.log_retention_days

  # ECR
  ecr_repository_url  = data.terraform_remote_state.foundation.outputs.pulumi_provisioner_ecr_url
  container_image_tag = var.pulumi_container_tag

  # Networking (Portal VPC for RDS access)
  vpc_id             = module.vpc.vpc_id
  private_subnet_ids = module.vpc.private_subnet_ids

  # Database
  db_host        = module.rds.db_instance_address
  db_port        = 5432
  db_name        = var.db_name
  db_resource_id = module.rds.db_resource_id

  # RDS security group (for adding ingress rule)
  rds_security_group_id = module.rds.db_security_group_id

  # Pulumi state (from Range environment)
  pulumi_state_bucket          = data.terraform_remote_state.range.outputs.pulumi_state_bucket_name
  pulumi_state_bucket_arn      = data.terraform_remote_state.range.outputs.pulumi_state_bucket_arn
  pulumi_locks_table           = data.terraform_remote_state.range.outputs.pulumi_locks_table_name
  pulumi_locks_table_arn       = data.terraform_remote_state.range.outputs.pulumi_locks_table_arn
  pulumi_secrets_kms_key_arn   = data.terraform_remote_state.range.outputs.pulumi_secrets_kms_key_arn
  pulumi_secrets_kms_key_alias = data.terraform_remote_state.range.outputs.pulumi_secrets_kms_key_alias

  # Range VPC configuration
  range_vpc_id                = data.terraform_remote_state.range.outputs.vpc_id
  range_vpc_cidr              = data.terraform_remote_state.range.outputs.vpc_cidr
  range_route_table_id        = data.terraform_remote_state.range.outputs.private_route_table_id
  range_availability_zone     = data.terraform_remote_state.range.outputs.availability_zone
  victim_security_group_id    = data.terraform_remote_state.range.outputs.victim_security_group_id
  kali_security_group_id      = data.terraform_remote_state.range.outputs.kali_security_group_id
  range_instance_profile_arn  = data.terraform_remote_state.range.outputs.range_instance_profile_arn
  range_instance_profile_name = data.terraform_remote_state.range.outputs.range_instance_profile_name
  range_instance_role_arn     = data.terraform_remote_state.range.outputs.range_instance_role_arn

  # AMIs
  kali_ami_id    = var.kali_ami_id
  victim_ami_id  = var.victim_ami_id
  windows_ami_id = var.windows_ami_id

  # Instance types
  kali_instance_type   = var.kali_instance_type
  victim_instance_type = var.victim_instance_type

  # S3
  agent_s3_bucket     = module.s3.bucket_name
  agent_s3_bucket_arn = module.s3.bucket_arn
}

# ------------------------------------------------------------------------------
# Log Aggregation (S3, SQS, Firehose for internal observability)
# Note: XDR CloudTrail integration is managed via CloudFormation, not Terraform
# ------------------------------------------------------------------------------

module "log_aggregation" {
  source = "../../../modules/log-aggregation"

  name_prefix            = local.name_prefix
  environment            = var.environment
  aws_region             = var.aws_region
  log_retention_days     = var.log_retention_days
  enable_log_aggregation = var.enable_log_aggregation

  # Phase 5: ALB and WAF logging
  enable_alb_access_logs = var.enable_alb_access_logs
  enable_waf_logging     = var.enable_waf_logging

  # Log group sources (for CloudWatch subscription filters)
  source_log_group_names = var.enable_log_aggregation ? concat(
    [module.ec2.log_group_name],
    [module.cognito.log_group_name],
    # Phase 5: VPC flow logs and RDS logs
    var.enable_vpc_flow_logs ? [module.vpc.flow_logs_log_group_name] : [],
    var.enable_rds_log_exports ? module.rds.log_group_names : [],
    # Pulumi provisioner logs
    module.pulumi_provisioner.log_group_names,
  ) : []

  tags = var.tags
}
