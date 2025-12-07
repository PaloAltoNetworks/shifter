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
    bucket = "shifter-infra-eedf1871-f634-4712-981a-5c6ba0738704"
    key    = "shifter/prod/terraform.tfstate"
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
  db_secret_arn         = module.rds.db_credentials_secret_arn
  app_port              = var.app_port
  root_volume_size      = var.ec2_root_volume_size

  tags = var.tags
}

# ------------------------------------------------------------------------------
# ALB Target Attachment (after EC2 is created)
# ------------------------------------------------------------------------------

resource "aws_lb_target_group_attachment" "portal" {
  target_group_arn = module.alb.target_group_arn
  target_id        = module.ec2.instance_id
  port             = var.app_port
}
