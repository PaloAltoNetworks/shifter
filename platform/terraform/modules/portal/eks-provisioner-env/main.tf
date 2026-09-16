# EKS provisioner-env assembly (ADR-044-R6)
#
# Consumer side of the cross-stack contract. Composes the provisioner Job
# environment for the AWS EKS control plane from:
#   - the range topology contract published at /shifter/<env>/range/* (opaque IDs
#     the range stack owns; SSM is the explicit interface);
#   - the shared portal data plane read via native AWS data sources (RDS, secrets
#     KMS, agent bucket, portal VPC + peering) by stable identifier;
#   - the prebaked AMI pointers at /shifter/ami/*;
#   - the management-plane runtime_env supplied by the deploy tooling.
#
# The merged map is rendered into the backend-neutral chart's runtimeEnv, and
# the provisioner IRSA role receives the shared provisioner-iam policy set. This
# is the AWS mirror of GCP's consumer-side render_runtime_env.py. It never uses
# terraform_remote_state (ADR-044-R6) and carries no secret payloads.

data "aws_ssm_parameters_by_path" "range" {
  path            = "/shifter/${var.environment}/range/"
  recursive       = true
  with_decryption = false
}

data "aws_ssm_parameter" "kali_ami" {
  name            = "/shifter/ami/kali"
  with_decryption = false
}

data "aws_ssm_parameter" "victim_ami" {
  name            = "/shifter/ami/ubuntu"
  with_decryption = false
}

data "aws_ssm_parameter" "windows_ami" {
  name            = "/shifter/ami/windows"
  with_decryption = false
}

data "aws_ssm_parameter" "dc_ami" {
  name            = "/shifter/ami/dc"
  with_decryption = false
}

# Shared portal data plane, read by stable identifier (name-discoverable, so no
# producer publish step is required for these — ADR-044-R6).
data "aws_db_instance" "portal" {
  db_instance_identifier = "${var.name_prefix}-db"
}

data "aws_kms_alias" "secrets_manager" {
  name = "alias/shifter-${var.environment}-secrets-manager"
}

data "aws_s3_bucket" "storage" {
  bucket = var.storage_bucket_name
}

data "aws_vpc" "portal" {
  tags = {
    Name = "${var.name_prefix}-vpc"
  }
}

data "aws_vpc_peering_connection" "portal_to_range" {
  vpc_id      = data.aws_vpc.portal.id
  peer_vpc_id = local.range_vpc_id
}

locals {
  # Flatten the range SSM contract into { <output-name> => <value> }, stripping
  # the /shifter/<env>/range/ prefix. Absent keys (skipped empty exports) default
  # to "" at read time, mirroring the portal root's `x != null ? x : ""`.
  range_prefix = "/shifter/${var.environment}/range/"
  range = {
    for name, value in zipmap(
      data.aws_ssm_parameters_by_path.range.names,
      nonsensitive(data.aws_ssm_parameters_by_path.range.values),
    ) : trimprefix(name, local.range_prefix) => value
  }

  range_vpc_id = lookup(local.range, "vpc_id", "")

  # Assembled provisioner Job environment. Mirrors the ECS task-definition env
  # (engine-provisioner/task_definition.tf) so the AWS provisioner behaves
  # identically whether dispatched to ECS (legacy) or an EKS Kubernetes Job.
  # DB_PASSWORD / FIELD_ENCRYPTION_KEY are absent by design: the provisioner
  # authenticates to RDS with IAM auth, and DC_DOMAIN_PASSWORD flows as a secret
  # reference, never here.
  provisioner_env = {
    SECRETS_KMS_KEY_ARN = data.aws_kms_alias.secrets_manager.target_key_arn
    DB_HOST             = data.aws_db_instance.portal.address
    DB_PORT             = "5432"
    DB_NAME             = var.db_name
    DB_USER             = "provisioner_lambda"
    STATE_BUCKET_URL    = "s3://${lookup(local.range, "engine_state_bucket_name", "")}"

    RANGE_VPC_ID                                  = local.range_vpc_id
    RANGE_VPC_CIDR                                = lookup(local.range, "vpc_cidr", "")
    RANGE_ROUTE_TABLE_ID                          = lookup(local.range, "private_route_table_id", "")
    RANGE_AVAILABILITY_ZONE                       = lookup(local.range, "availability_zone", "")
    RANGE_VPN_EDGE_SUBNET_ID                      = lookup(local.range, "vpn_edge_subnet_id", "")
    RANGE_VPN_GATEWAY_PERMISSIONS_BOUNDARY_ARN    = var.permissions_boundary_arn
    RANGE_VPN_PROVIDER_ENDPOINT_SECURITY_GROUP_ID = lookup(local.range, "provider_api_endpoint_security_group_id", "")
    RANGE_INSTANCE_PROFILE_NAME                   = lookup(local.range, "range_instance_profile_name", "")
    RANGE_INSTANCE_ROLE_ARN                       = lookup(local.range, "range_instance_role_arn", "")

    KALI_AMI_ID    = nonsensitive(data.aws_ssm_parameter.kali_ami.value)
    VICTIM_AMI_ID  = nonsensitive(data.aws_ssm_parameter.victim_ami.value)
    WINDOWS_AMI_ID = nonsensitive(data.aws_ssm_parameter.windows_ami.value)
    DC_AMI_ID      = nonsensitive(data.aws_ssm_parameter.dc_ami.value)
    DC_DOMAIN_NAME = var.dc_domain_name

    AGENT_S3_BUCKET           = data.aws_s3_bucket.storage.bucket
    S3_ENDPOINT_ID            = lookup(local.range, "s3_endpoint_id", "")
    FIREWALL_ENDPOINT_ID      = lookup(local.range, "firewall_endpoint_id", "")
    RANGE_EGRESS_MODE         = lookup(local.range, "range_egress_mode", "allowlist")
    SSM_ENDPOINTS_SUBNET_CIDR = lookup(local.range, "ssm_endpoints_subnet_cidr", "")
    PORTAL_VPC_CIDR           = data.aws_vpc.portal.cidr_block
    PORTAL_VPC_PEERING_ID     = data.aws_vpc_peering_connection.portal_to_range.id

    KALI_INSTANCE_TYPE   = var.kali_instance_type
    VICTIM_INSTANCE_TYPE = var.victim_instance_type

    NGFW_AMI_ID                 = lookup(local.range, "ngfw_ami_id", "")
    NGFW_INSTANCE_TYPE          = lookup(local.range, "ngfw_instance_type", "")
    NGFW_MGMT_SECURITY_GROUP_ID = lookup(local.range, "ngfw_mgmt_security_group_id", "")
    NGFW_DATA_SECURITY_GROUP_ID = lookup(local.range, "ngfw_data_security_group_id", "")
    NGFW_VPC_ID                 = local.range_vpc_id
    NGFW_SUBNET_ID              = lookup(local.range, "ngfw_subnet_id", "")
    NGFW_SUBNET_CIDR            = lookup(local.range, "ngfw_subnet_cidr", "")
    NGFW_BOOTSTRAP_BUCKET       = data.aws_s3_bucket.storage.bucket
    NGFW_INSTANCE_PROFILE_NAME  = lookup(local.range, "ngfw_instance_profile_name", "")
  }

  # runtime_env (mgmt) first, then the assembled provisioner env, then any
  # deployment extras (e.g. AWS_POLARIS_AGENT_*). Later maps win on conflict.
  merged_runtime_env = merge(var.runtime_env, local.provisioner_env, var.extra_env)
}

# The provisioner IRSA role receives the substrate-neutral provisioner permission
# set (the same module the ECS task role uses), sourced from the range contract
# and the shared portal data plane.
module "provisioner_iam" {
  source = "../../provisioner-iam"

  name_prefix              = var.name_prefix
  environment              = var.environment
  role_name                = var.provisioner_role_name
  role_id                  = var.provisioner_role_id
  permissions_boundary_arn = var.permissions_boundary_arn

  engine_state_bucket_arn    = lookup(local.range, "engine_state_bucket_arn", "")
  engine_locks_table_arn     = lookup(local.range, "engine_locks_table_arn", "")
  engine_secrets_kms_key_arn = lookup(local.range, "engine_secrets_kms_key_arn", "")

  secrets_manager_kms_key_arn = data.aws_kms_alias.secrets_manager.target_key_arn
  db_resource_id              = data.aws_db_instance.portal.resource_id
  agent_s3_bucket_arn         = data.aws_s3_bucket.storage.arn

  range_vpc_id            = local.range_vpc_id
  range_availability_zone = lookup(local.range, "availability_zone", "")
  range_instance_role_arn = lookup(local.range, "range_instance_role_arn", "")
  ngfw_instance_role_arn  = lookup(local.range, "ngfw_instance_role_arn", "")

  tags = var.tags
}
