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
    bucket = "shifter-infra-eedf1871-f634-4712-981a-5c6ba0738704"
    key    = "shifter/prod/terraform.tfstate"
    region = "us-east-2"
  }
}

# ------------------------------------------------------------------------------
# Remote State - Range VPC
# ------------------------------------------------------------------------------

data "terraform_remote_state" "range" {
  backend = "s3"
  config = {
    bucket = "shifter-infra-eedf1871-f634-4712-981a-5c6ba0738704"
    key    = "prod/range/terraform.tfstate"
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
# Cognito
# ------------------------------------------------------------------------------

module "cognito" {
  source = "../../../modules/portal/cognito"

  name_prefix           = local.name_prefix
  aws_region            = var.aws_region
  cognito_domain_prefix = var.cognito_domain_prefix
  callback_urls         = ["https://${var.domain_name}/oidc/callback/"]
  logout_urls           = ["https://${var.domain_name}/"]
  allowed_email_domains = var.allowed_email_domains
  allowed_emails        = var.allowed_emails
  deletion_protection   = true

  # AgentChat (OpenWebUI) OAuth callback - served at subdomain
  agentchat_callback_urls = ["https://chat.${var.domain_name}/oauth/oidc/callback"]
  agentchat_logout_urls   = ["https://chat.${var.domain_name}/"]

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
  step_function_arns = [
    module.provisioner.provision_range_state_machine_arn,
    module.provisioner.teardown_range_state_machine_arn,
  ]

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
# OpenWebUI Database Credentials
# ------------------------------------------------------------------------------
# OpenWebUI uses a separate database in the same RDS instance.
# After terraform apply, manually create the database and user:
#   CREATE DATABASE openwebui;
#   CREATE USER openwebui WITH PASSWORD '<from-secrets-manager>';
#   GRANT ALL PRIVILEGES ON DATABASE openwebui TO openwebui;
#   \c openwebui
#   GRANT ALL ON SCHEMA public TO openwebui;

resource "random_password" "openwebui_db_password" {
  length  = 32
  special = false
}

# checkov:skip=CKV_AWS_149:AWS-managed keys sufficient for internal MVP. See #213
resource "aws_secretsmanager_secret" "openwebui_db" {
  name                    = "shifter-${local.name_prefix}-openwebui-db"
  description             = "OpenWebUI PostgreSQL database credentials"
  recovery_window_in_days = 0

  tags = merge(var.tags, {
    Name = "shifter-${local.name_prefix}-openwebui-db"
  })
}

resource "aws_secretsmanager_secret_version" "openwebui_db" {
  secret_id = aws_secretsmanager_secret.openwebui_db.id
  secret_string = jsonencode({
    username     = "openwebui"
    password     = random_password.openwebui_db_password.result
    host         = module.rds.db_instance_address
    port         = 5432
    dbname       = "openwebui"
    database_url = "postgresql://openwebui:${random_password.openwebui_db_password.result}@${module.rds.db_instance_address}:5432/openwebui"
  })
}

# ------------------------------------------------------------------------------
# Provisioner (Step Functions + Lambda for range provisioning)
# ------------------------------------------------------------------------------

module "provisioner" {
  source = "../../../modules/range/provisioner"

  name_prefix = local.name_prefix
  environment = var.environment
  tags        = var.tags

  # Portal VPC (where Lambda runs)
  portal_vpc_id     = module.vpc.vpc_id
  portal_subnet_ids = module.vpc.private_subnet_ids

  # Range VPC (where resources are created)
  range_vpc_id         = data.terraform_remote_state.range.outputs.vpc_id
  range_route_table_id = data.terraform_remote_state.range.outputs.private_route_table_id
  # Extract CIDR prefix from VPC CIDR (e.g., "10.1.0.0/16" -> "10.1")
  range_cidr_prefix = join(".", slice(split(".", data.terraform_remote_state.range.outputs.vpc_cidr), 0, 2))
  availability_zone = module.vpc.availability_zones[0]

  # RDS Configuration (IAM DB auth)
  db_host               = module.rds.db_instance_address
  db_port               = 5432
  db_name               = var.db_name
  db_resource_id        = module.rds.db_resource_id
  rds_security_group_id = module.rds.db_security_group_id

  # Victim Configuration
  victim_ami_id            = var.victim_ami_id
  victim_instance_type     = var.victim_instance_type
  victim_security_group_id = data.terraform_remote_state.range.outputs.victim_security_group_id
  agent_s3_bucket          = var.user_storage_bucket

  # Kali Configuration
  kali_ami_id            = var.kali_ami_id
  kali_instance_type     = var.kali_instance_type
  kali_security_group_id = data.terraform_remote_state.range.outputs.kali_security_group_id

  # Monitoring Configuration
  enable_alarms = var.enable_provisioner_alarms
  alarm_email   = var.provisioner_alarm_email

  # Chat URL for MCP integration (subdomain - no /chat path needed)
  chat_base_url = "https://chat.${var.domain_name}"
}
