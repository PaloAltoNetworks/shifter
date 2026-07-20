# ------------------------------------------------------------------------------
# Core Variables
# ------------------------------------------------------------------------------

variable "name_prefix" {
  description = "Prefix for resource names"
  type        = string
}

variable "iam_name_prefix" {
  description = "Prefix for IAM role and instance profile names (defaults to name_prefix)"
  type        = string
  default     = null
}

variable "environment" {
  description = "Environment name (dev, prod)"
  type        = string
}

# Renderer-owned backend selection (PLAT-2005). Derived from shifter.yaml at
# deploy time (shifter-config render-runtime) and received here as a plain
# Terraform variable, not synthesized in this module. No default: a missing
# cloud_provider.auto.tfvars must fail the plan loudly rather than silently
# defaulting to "aws".
variable "cloud_provider" {
  description = "Backend identity injected into the provisioner's CLOUD_PROVIDER env var. Rendered from shifter.yaml's settings.backend by shifter-config render-runtime; must not be hardcoded or defaulted here."
  type        = string
}

variable "tags" {
  description = "Tags to apply to all resources"
  type        = map(string)
  default     = {}
}

variable "log_retention_days" {
  description = "CloudWatch log retention in days"
  type        = number
  default     = 30
}

# ------------------------------------------------------------------------------
# ECS Configuration
# ------------------------------------------------------------------------------

variable "ecr_repository_url" {
  description = "URL of the ECR repository for the engine provisioner image"
  type        = string
}

variable "container_image_tag" {
  description = "Bootstrap Docker image tag for the engine provisioner container when no digest is supplied"
  type        = string
  default     = "latest"
}

variable "container_image_digest" {
  description = "Immutable Docker image digest for the engine provisioner container"
  type        = string
  default     = ""
}

variable "task_cpu" {
  description = "CPU units for the ECS task (1024 = 1 vCPU)"
  type        = number
  default     = 1024
}

variable "task_memory" {
  description = "Memory in MB for the ECS task"
  type        = number
  default     = 2048
}

# ------------------------------------------------------------------------------
# Networking
# ------------------------------------------------------------------------------

variable "vpc_id" {
  description = "ID of the Portal VPC where ECS tasks run"
  type        = string
}

variable "private_subnet_ids" {
  description = "List of private subnet IDs for ECS tasks"
  type        = list(string)
}

# ------------------------------------------------------------------------------
# Database (RDS IAM Auth)
# ------------------------------------------------------------------------------

variable "db_host" {
  description = "RDS database hostname"
  type        = string
}

variable "db_port" {
  description = "RDS database port"
  type        = number
  default     = 5432
}

variable "db_name" {
  description = "RDS database name"
  type        = string
}

variable "db_resource_id" {
  description = "RDS resource ID for IAM authentication"
  type        = string
}

variable "rds_security_group_id" {
  description = "Security group ID of the RDS instance"
  type        = string
}

# ------------------------------------------------------------------------------
# Engine State Backend
# ------------------------------------------------------------------------------

variable "engine_state_bucket" {
  description = "S3 bucket name for engine state"
  type        = string
}

variable "engine_state_bucket_arn" {
  description = "S3 bucket ARN for engine state"
  type        = string
}

variable "engine_locks_table" {
  description = "DynamoDB table name for engine locking"
  type        = string
}

variable "engine_locks_table_arn" {
  description = "DynamoDB table ARN for engine locking"
  type        = string
}

variable "engine_secrets_kms_key_arn" {
  description = "ARN of the KMS key for engine secrets encryption"
  type        = string
}

variable "engine_secrets_kms_key_alias" {
  description = "Alias of the KMS key for engine secrets encryption"
  type        = string
}

variable "secrets_manager_kms_key_arn" {
  description = "ARN of the portal Secrets Manager CMK used to encrypt the DC domain password and any future module-owned Secrets Manager secrets (CKV_AWS_149). Distinct from engine_secrets_kms_key_arn, which is the Pulumi state CMK and must not be reused for Secrets Manager. Required input — no default."
  type        = string
}

# ------------------------------------------------------------------------------
# Range VPC Configuration
# ------------------------------------------------------------------------------

variable "range_vpc_id" {
  description = "ID of the Range VPC where instances are provisioned"
  type        = string
}

variable "range_vpc_cidr" {
  description = "CIDR block of the Range VPC"
  type        = string
}

variable "range_route_table_id" {
  description = "Route table ID for range subnets"
  type        = string
}

variable "range_availability_zone" {
  description = "Availability zone for range subnets (e.g., us-east-2a)"
  type        = string
}

variable "range_vpn_edge_subnet_id" {
  description = "Public Range VPC subnet used by per-range OpenVPN NLBs"
  type        = string
  default     = ""
}

variable "range_vpn_provider_endpoint_security_group_id" {
  description = "Destination security group for Range VPC private provider API endpoints"
  type        = string
  default     = ""
}

variable "range_instance_profile_arn" {
  description = "IAM instance profile ARN for range instances"
  type        = string
}

variable "range_instance_profile_name" {
  description = "IAM instance profile name for range instances"
  type        = string
}

variable "range_instance_role_arn" {
  description = "IAM role ARN for range instances (required for iam:PassRole)"
  type        = string
}

# ------------------------------------------------------------------------------
# AMI IDs
# ------------------------------------------------------------------------------

variable "kali_ami_id" {
  description = "AMI ID for Kali Linux instances"
  type        = string
}

variable "victim_ami_id" {
  description = "AMI ID for Linux victim instances"
  type        = string
}

variable "windows_ami_id" {
  description = "AMI ID for Windows victim instances"
  type        = string
  default     = ""
}

variable "dc_ami_id" {
  description = "AMI ID for Domain Controller instances (prebaked with AD DS promoted)"
  type        = string
  default     = ""
}

variable "dc_domain_name" {
  description = "Domain name for prebaked DC (e.g., internal.shifter)"
  type        = string
  default     = "internal.shifter"
}

# The DC Administrator password is intentionally NOT a Terraform variable.
# It lives in aws_secretsmanager_secret.dc_domain_password (see secrets.tf)
# with the value managed out-of-band, and is injected into the engine
# provisioner ECS task via the `secrets = [...]` block in
# task_definition.tf. The portal Django container receives the value
# through the same secret, plumbed through the portal/ssm and portal/ec2
# modules and resolved at startup by entrypoint.sh.

# ------------------------------------------------------------------------------
# Instance Types
# ------------------------------------------------------------------------------

variable "kali_instance_type" {
  description = "EC2 instance type for Kali attacker instances"
  type        = string
}

variable "victim_instance_type" {
  description = "EC2 instance type for victim instances"
  type        = string
}

# ------------------------------------------------------------------------------
# S3 Agent Bucket
# ------------------------------------------------------------------------------

variable "agent_s3_bucket" {
  description = "S3 bucket name for XDR agent installers"
  type        = string
}

variable "agent_s3_bucket_arn" {
  description = "S3 bucket ARN for XDR agent installers"
  type        = string
}

variable "s3_endpoint_id" {
  description = "VPC Gateway Endpoint ID for S3 access from range subnets"
  type        = string
  default     = ""
}

variable "firewall_endpoint_id" {
  description = "AWS Network Firewall endpoint ID for internet egress from range subnets"
  type        = string
  default     = ""
}

variable "range_egress_mode" {
  description = "Runtime route-table egress posture for participant subnets (bridge for shifter.yaml settings.range_egress.mode)"
  type        = string
  default     = "allowlist"

  validation {
    condition     = contains(["allowlist", "none"], var.range_egress_mode)
    error_message = "range_egress_mode must be one of: allowlist, none."
  }
}

variable "ssm_endpoints_subnet_cidr" {
  description = "CIDR block of the SSM/Bedrock endpoints subnet (for NGFW routing)"
  type        = string
  default     = ""
}

# ------------------------------------------------------------------------------
# Portal VPC Configuration (for terminal SSH access)
# ------------------------------------------------------------------------------

variable "portal_vpc_cidr" {
  description = "CIDR block of the Portal VPC for SSH access routing"
  type        = string
  default     = ""
}

variable "portal_vpc_peering_id" {
  description = "VPC peering connection ID between Portal and Range VPCs"
  type        = string
  default     = ""
}

# ------------------------------------------------------------------------------
# NGFW (VM-Series) Configuration
# ------------------------------------------------------------------------------

variable "ngfw_mgmt_security_group_id" {
  description = "Security group ID for NGFW management ENI (SSH, HTTPS from portal)"
  type        = string
  default     = ""
}

variable "ngfw_data_security_group_id" {
  description = "Security group ID for NGFW data ENI (all traffic from VPC for GENEVE)"
  type        = string
  default     = ""
}

variable "ngfw_ami_id" {
  description = "AMI ID for VM-Series NGFW instances (empty if NGFW disabled)"
  type        = string
  default     = ""
}

variable "ngfw_instance_type" {
  description = "EC2 instance type for VM-Series NGFW instances"
  type        = string
  default     = "m5.xlarge"
}

variable "ngfw_subnet_id" {
  description = "Subnet ID for VM-Series NGFW instances"
  type        = string
  default     = ""
}

variable "ngfw_subnet_cidr" {
  description = "CIDR block for NGFW subnet (for VPC gateway IP calculation)"
  type        = string
  default     = ""
}

variable "ngfw_instance_profile_name" {
  description = "IAM instance profile name for VM-Series NGFW instances (for S3 bootstrap access)"
  type        = string
  default     = ""
}

variable "ngfw_instance_role_arn" {
  description = "IAM role ARN for NGFW instances (required for iam:PassRole)"
  type        = string
  default     = ""
}

# ------------------------------------------------------------------------------
# Alarms Configuration
# ------------------------------------------------------------------------------

variable "enable_alarms" {
  description = "Enable CloudWatch alarms for range launch failures"
  type        = bool
  default     = false
}

variable "alarm_email" {
  description = "Email address for alarm notifications (leave empty to skip)"
  type        = string
  default     = ""
}

# ------------------------------------------------------------------------------
# Messaging (SNS)
# ------------------------------------------------------------------------------

variable "sns_topic_arn" {
  description = "ARN of the SNS topic for range event publishing"
  type        = string
}

variable "sns_kms_key_arn" {
  description = "ARN of the CMK used by the encrypted SNS range-events topic"
  type        = string
}

variable "permissions_boundary_arn" {
  description = "Permissions boundary ARN required on CI-created shifter-* roles"
  type        = string
}

# ------------------------------------------------------------------------------
# Polaris Bedrock Agent Config (#1377)
# ------------------------------------------------------------------------------
# Threaded into the ECS task container as AWS_POLARIS_AGENT_* env vars,
# consumed by shifter/engine/provisioner/config.py's
# load_aws_polaris_agent_config(). All default to empty/zero so the
# feature stays off until populated per-environment via the deploy
# secrets mechanism; enablement is signaled by
# aws_polaris_agent_main_inference_profile_arn being non-empty. Do not
# hardcode account-specific ARNs here.

variable "aws_polaris_agent_region" {
  description = "AWS region for Bedrock Polaris agent invocation"
  type        = string
  default     = ""
}

variable "aws_polaris_agent_main_model_id" {
  description = "Bedrock model ID for the Polaris agent's main model"
  type        = string
  default     = ""
}

variable "aws_polaris_agent_small_model_id" {
  description = "Bedrock model ID for the Polaris agent's small/fast model"
  type        = string
  default     = ""
}

variable "aws_polaris_agent_main_inference_profile_arn" {
  description = "Approved Bedrock inference-profile ARN for the main model. Non-empty is the Polaris agent feature's enablement signal."
  type        = string
  default     = ""
}

variable "aws_polaris_agent_small_inference_profile_arn" {
  description = "Approved Bedrock inference-profile ARN for the small/fast model"
  type        = string
  default     = ""
}

variable "aws_polaris_agent_main_backing_model_arns" {
  description = "Backing Bedrock foundation-model ARNs for the main inference profile"
  type        = list(string)
  default     = []
}

variable "aws_polaris_agent_small_backing_model_arns" {
  description = "Backing Bedrock foundation-model ARNs for the small/fast inference profile"
  type        = list(string)
  default     = []
}

variable "aws_polaris_agent_sts_session_duration_seconds" {
  description = "STS AssumeRole session duration for the Polaris agent role, in seconds (AWS minimum is 900)"
  type        = number
  default     = 0
}

variable "aws_polaris_agent_refresh_window_seconds" {
  description = "Seconds before STS session expiry at which the range host refreshes Polaris agent credentials"
  type        = number
  default     = 0
}
