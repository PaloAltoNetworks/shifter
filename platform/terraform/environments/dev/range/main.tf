terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

data "aws_caller_identity" "current" {}

locals {
  name_prefix                      = "${var.environment}-range"
  iam_name_prefix                  = "shifter-${var.environment}-range"
  ci_role_permissions_boundary_arn = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:policy/shifter-${var.environment}-ci-role-boundary"
}

# ------------------------------------------------------------------------------
# Range VPC
# ------------------------------------------------------------------------------

module "vpc" {
  source = "../../../modules/range/vpc"

  name_prefix              = local.name_prefix
  iam_name_prefix          = local.iam_name_prefix
  environment              = var.environment
  permissions_boundary_arn = local.ci_role_permissions_boundary_arn
  vpc_cidr                 = var.vpc_cidr
  portal_vpc_cidr          = var.portal_vpc_cidr
  tags                     = var.tags

  # Phase 5: VPC Flow Logs
  enable_flow_logs = var.enable_flow_logs

  # Range Instance IAM
  agent_s3_bucket = var.agent_s3_bucket

  # VM-Series NGFW
  vm_series_ami_id        = var.vm_series_ami_id
  vm_series_instance_type = var.vm_series_instance_type

  # Persistent NGFW Infrastructure
  enable_ngfw_infrastructure = var.enable_ngfw_infrastructure

  # Network Firewall IP Allowlist
  victim_allowed_cidrs = var.victim_allowed_cidrs

  # Network Firewall lifecycle (mirrors db_deletion_protection root-var / tfvars convention)
  network_firewall_delete_protection = var.network_firewall_delete_protection
}

# ------------------------------------------------------------------------------
# Engine State Backend (S3 + DynamoDB)
# ------------------------------------------------------------------------------

module "engine_state" {
  source = "../../../modules/engine-state"

  name_prefix        = local.name_prefix
  environment        = var.environment
  tags               = var.tags
  log_retention_days = var.log_retention_days
}

moved {
  from = module.pulumi_state
  to   = module.engine_state
}

# ------------------------------------------------------------------------------
# Range SSM export (ADR-044-R6)
#
# Publish the range-owned provisioner-env contract to /shifter/<env>/range/* so
# the AWS EKS control plane can compose the provisioner Job environment without
# reaching into this stack's Terraform state. Non-secret identifiers only.
# ------------------------------------------------------------------------------

module "ssm_export" {
  source = "../../../modules/range/ssm-export"

  environment = var.environment
  tags        = var.tags

  parameters = {
    # Range network topology
    vpc_id                                  = module.vpc.vpc_id
    vpc_cidr                                = module.vpc.vpc_cidr
    availability_zone                       = module.vpc.availability_zone
    private_route_table_id                  = module.vpc.private_route_table_id
    vpn_edge_subnet_id                      = module.vpc.vpn_edge_subnet_id
    provider_api_endpoint_security_group_id = module.vpc.provider_api_endpoint_security_group_id
    s3_endpoint_id                          = module.vpc.s3_endpoint_id
    firewall_endpoint_id                    = module.vpc.firewall_endpoint_id != null ? module.vpc.firewall_endpoint_id : ""
    range_egress_mode                       = var.range_egress_mode
    ssm_endpoints_subnet_cidr               = module.vpc.ssm_endpoints_subnet_cidr

    # Range instance identity (provisioner iam:PassRole + task env)
    range_instance_role_arn     = module.vpc.range_instance_role_arn
    range_instance_profile_name = module.vpc.range_instance_profile_name

    # Engine state backend (Terraform state bucket + locks + secrets KMS)
    engine_state_bucket_name     = module.engine_state.bucket_name
    engine_state_bucket_arn      = module.engine_state.bucket_arn
    engine_locks_table_name      = module.engine_state.dynamodb_table_name
    engine_locks_table_arn       = module.engine_state.dynamodb_table_arn
    engine_secrets_kms_key_arn   = module.engine_state.secrets_kms_key_arn
    engine_secrets_kms_key_alias = module.engine_state.secrets_kms_key_alias

    # VM-Series NGFW (optional; empty when disabled → skipped by the module)
    ngfw_mgmt_security_group_id = module.vpc.ngfw_mgmt_security_group_id != null ? module.vpc.ngfw_mgmt_security_group_id : ""
    ngfw_data_security_group_id = module.vpc.ngfw_data_security_group_id != null ? module.vpc.ngfw_data_security_group_id : ""
    ngfw_ami_id                 = module.vpc.vm_series_ami_id
    ngfw_instance_type          = var.vm_series_instance_type
    ngfw_subnet_id              = module.vpc.ngfw_subnet_id != null ? module.vpc.ngfw_subnet_id : ""
    ngfw_subnet_cidr            = module.vpc.ngfw_subnet_cidr != null ? module.vpc.ngfw_subnet_cidr : ""
    ngfw_instance_role_arn      = module.vpc.ngfw_instance_role_arn != null ? module.vpc.ngfw_instance_role_arn : ""
    ngfw_instance_profile_name  = module.vpc.ngfw_instance_profile_name != null ? module.vpc.ngfw_instance_profile_name : ""
  }
}
