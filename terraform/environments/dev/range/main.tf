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
}

# ------------------------------------------------------------------------------
# Pulumi State Backend (S3 + DynamoDB)
# ------------------------------------------------------------------------------

module "pulumi_state" {
  source = "../../../modules/pulumi-state"
  count  = var.enable_pulumi_provisioner ? 1 : 0

  name_prefix        = local.name_prefix
  environment        = var.environment
  tags               = var.tags
  log_retention_days = var.log_retention_days
}
