terraform {
  required_version = ">= 1.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

locals {
  name_prefix = "${var.environment}-range"
}

# ------------------------------------------------------------------------------
# Range VPC
# ------------------------------------------------------------------------------

module "vpc" {
  source = "../../../modules/range/vpc"

  name_prefix     = local.name_prefix
  vpc_cidr        = var.vpc_cidr
  portal_vpc_cidr = var.portal_vpc_cidr
  tags            = var.tags

  # Phase 5: VPC Flow Logs
  enable_flow_logs = var.enable_flow_logs

  # Range Instance IAM
  agent_s3_bucket = var.agent_s3_bucket

  # VM-Series NGFW
  vm_series_ami_id        = var.vm_series_ami_id
  vm_series_instance_type = var.vm_series_instance_type

  # Persistent NGFW Infrastructure
  enable_ngfw_infrastructure = var.enable_ngfw_infrastructure
}

# ------------------------------------------------------------------------------
# Pulumi State Backend (S3 + DynamoDB)
# ------------------------------------------------------------------------------

module "pulumi_state" {
  source = "../../../modules/pulumi-state"

  name_prefix        = local.name_prefix
  environment        = var.environment
  tags               = var.tags
  log_retention_days = var.log_retention_days
}

# ------------------------------------------------------------------------------
# OpenBAS Shared Infrastructure
# ------------------------------------------------------------------------------

module "openbas" {
  count  = var.enable_openbas ? 1 : 0
  source = "../../../modules/openbas"

  name_prefix            = local.name_prefix
  vpc_id                 = module.vpc.vpc_id
  vpc_cidr               = var.vpc_cidr
  portal_vpc_cidr        = var.portal_vpc_cidr
  private_route_table_id = module.vpc.private_route_table_id
  tags                   = var.tags

  # OpenBAS configuration
  base_url      = var.openbas_base_url
  openbas_image = var.openbas_image

  # ECS configuration
  task_cpu           = var.openbas_task_cpu
  task_memory        = var.openbas_task_memory
  desired_count      = var.openbas_desired_count
  enable_autoscaling = var.openbas_enable_autoscaling
  min_capacity       = var.openbas_min_capacity
  max_capacity       = var.openbas_max_capacity

  # Database configuration
  db_instance_class        = var.openbas_db_instance_class
  db_multi_az              = var.openbas_db_multi_az
  db_backup_retention_days = var.openbas_db_backup_retention_days
  db_deletion_protection   = var.openbas_db_deletion_protection
  db_skip_final_snapshot   = var.openbas_db_skip_final_snapshot

  # Logging
  log_retention_days = var.log_retention_days
}
