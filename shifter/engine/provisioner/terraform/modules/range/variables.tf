# Core identifiers
variable "range_id" {
  description = "Range database ID"
  type        = number
}

variable "user_id" {
  description = "Owner's Django user ID"
  type        = number
}

variable "request_uuid" {
  description = "Provisioning request UUID for state isolation"
  type        = string
}

variable "openvpn_access" {
  description = "Server-issued OpenVPN capability; null means this range is not authorized for a VPN edge"
  type = object({
    version     = string
    channel     = string
    target_ref  = string
    teardown_at = string
  })
  default = null
}

variable "environment" {
  description = "Environment name (dev, staging, prod)"
  type        = string
  default     = "dev"
}

variable "secrets_kms_key_arn" {
  description = "ARN of the portal Secrets Manager CMK used to encrypt range instance SSH-key secrets at runtime (CKV_AWS_149). Sourced from the engine-provisioner ECS task env (SECRETS_KMS_KEY_ARN) which is wired from the platform env root."
  type        = string
}

variable "vpn_edge_subnet_id" {
  description = "Public edge subnet used only by the per-range OpenVPN network load balancer"
  type        = string
  default     = ""
}

variable "vpn_gateway_permissions_boundary_arn" {
  description = "Permissions boundary for the request-owned OpenVPN gateway role"
  type        = string
  default     = ""
}

variable "vpn_provider_endpoint_security_group_id" {
  description = "Destination security group for private provider API endpoints"
  type        = string
  default     = ""
}

variable "vpn_public_client_cidr" {
  description = "Audited public client source for the per-range mutual-TLS OpenVPN UDP listener (ADR-039-R10)"
  type        = string
  default     = "0.0.0.0/0"

  validation {
    condition     = can(cidrnetmask(var.vpn_public_client_cidr))
    error_message = "vpn_public_client_cidr must be a valid IPv4 CIDR."
  }
}

# VPC configuration
variable "vpc_id" {
  description = "Range VPC ID"
  type        = string
}

variable "vpc_cidr" {
  description = "Range VPC CIDR block"
  type        = string
}

variable "availability_zone" {
  description = "AZ for all range resources"
  type        = string
}

# Network integration
variable "s3_endpoint_id" {
  description = "S3 Gateway VPC Endpoint ID for agent downloads"
  type        = string
  default     = ""
}

variable "firewall_endpoint_id" {
  description = "AWS Network Firewall endpoint ID for internet egress"
  type        = string
  default     = ""
}

variable "range_egress_mode" {
  description = "Runtime route-table egress posture for participant subnets (bridge for shifter.yaml settings.range_egress.mode). allowlist creates the firewall default route; none omits all 0.0.0.0/0 routes."
  type        = string
  default     = "allowlist"

  validation {
    condition     = contains(["allowlist", "none"], var.range_egress_mode)
    error_message = "range_egress_mode must be one of: allowlist, none."
  }
}

variable "portal_vpc_cidr" {
  description = "Portal VPC CIDR for SSH/RDP access"
  type        = string
  default     = ""
}

variable "portal_vpc_peering_id" {
  description = "VPC peering connection ID for portal route"
  type        = string
  default     = ""
}

variable "ngfw_data_eni_id" {
  description = "NGFW data ENI ID for inter-subnet routing (empty if no NGFW)"
  type        = string
  default     = ""
}

# AMI IDs
variable "kali_ami_id" {
  description = "AMI ID for Kali attacker instances"
  type        = string
}

variable "victim_ami_id" {
  description = "AMI ID for Linux victim instances (Ubuntu)"
  type        = string
}

variable "windows_ami_id" {
  description = "AMI ID for Windows victim instances"
  type        = string
}

variable "dc_ami_id" {
  description = "AMI ID for Domain Controller instances"
  type        = string
}

# Instance configuration
variable "instance_profile_name" {
  description = "IAM instance profile name for range instances"
  type        = string
  default     = ""
}

#------------------------------------------------------------------------------
# Polaris Bedrock Agent Role (#1377)
#------------------------------------------------------------------------------

variable "polaris_agent_enabled" {
  description = "Enable the per-range Polaris Bedrock agent role (docs/architecture/polaris-aws-agent-credentials-preflight-1377.md). Off by default; when true, range_instance_role_arn and the inference-profile/backing-model ARN variables below must be non-empty (enforced by a plan-time precondition on aws_iam_role.polaris_agent)."
  type        = bool
  default     = false
}

variable "range_instance_role_arn" {
  description = "ARN of the shared range-host IAM role (platform/terraform/modules/range/vpc aws_iam_role.range_instance). Trusted principal for the per-range Polaris agent role's assume-role policy; required when polaris_agent_enabled is true. Defaults to empty so existing non-Polaris applies are unaffected until the provisioner wires this through."
  type        = string
  default     = ""
}

variable "polaris_agent_main_inference_profile_arn" {
  description = "Approved Bedrock inference-profile ARN for the main model. Required (non-empty) when polaris_agent_enabled is true."
  type        = string
  default     = ""
}

variable "polaris_agent_small_inference_profile_arn" {
  description = "Approved Bedrock inference-profile ARN for the small/fast model. Required (non-empty) when polaris_agent_enabled is true."
  type        = string
  default     = ""
}

variable "polaris_agent_main_backing_model_arns" {
  description = "Backing Bedrock foundation-model ARNs for the main inference profile. Required (non-empty) when polaris_agent_enabled is true."
  type        = list(string)
  default     = []
}

variable "polaris_agent_small_backing_model_arns" {
  description = "Backing Bedrock foundation-model ARNs for the small/fast inference profile. Required (non-empty) when polaris_agent_enabled is true."
  type        = list(string)
  default     = []
}

variable "polaris_agent_permissions_boundary_arn" {
  description = "Permissions boundary ARN applied unconditionally to the per-range Polaris agent role's permissions_boundary argument. REQUIRED (non-empty) when polaris_agent_enabled is true, enforced by aws_iam_role.polaris_agent's lifecycle precondition (ADR-004-R21); empty is only valid while polaris_agent_enabled is false."
  type        = string
  default     = ""
}

# Subnets specification (JSON from Python)
variable "subnets" {
  description = "List of subnet configurations with pre-allocated CIDRs"
  type = list(object({
    name         = string
    uuid         = string
    cidr         = string # Pre-allocated CIDR from allocate_subnets()
    connected_to = list(string)
    instances = list(object({
      uuid                = string
      name                = string # Instance name from scenario template (e.g., "webdev01", "kali")
      role                = string # attacker, victim, dc
      os_type             = string # kali, ubuntu, windows
      instance_type       = string
      agent_presigned_url = string
      join_domain         = bool
      ami_id              = string # Per-instance AMI override; empty = use os_type lookup
    }))
  }))
}
