# VPC module variables - NO DEFAULTS

variable "name_prefix" {
  description = "Prefix for resource names (e.g., prod-portal)"
  type        = string
}

variable "iam_name_prefix" {
  description = "Prefix for IAM role and instance profile names (defaults to name_prefix)"
  type        = string
  default     = null
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC"
  type        = string
}

variable "az_count" {
  description = "Number of availability zones to use"
  type        = number

  # The VPC carves THREE /20 subnet tiers from vpc_cidr via
  # cidrsubnet(vpc_cidr, 4, N): public at index band [0 .. az_count-1],
  # private at [az_count .. 2*az_count-1], and public-workload at
  # [2*az_count .. 3*az_count-1] (#933). The portal inspection firewall
  # reserves /28 blocks via cidrsubnet(vpc_cidr, 12, 4080+i), which fall
  # inside /20 block 15. Bounding az_count <= 5 keeps all three /20 tiers
  # within blocks 0-14, leaving block 15 for the firewall, so every
  # subnet CIDR is unique and non-overlapping for any allowed az_count.
  # This is the structural proof that the public-workload index band does
  # not collide with an existing tier.
  validation {
    condition     = var.az_count >= 1 && var.az_count <= 5
    error_message = "az_count must be between 1 and 5 so the public, private, and public-workload /20 subnet tiers stay within cidrsubnet index blocks 0-14 and do not collide with each other or the inspection firewall /28 tier (block 15)."
  }
}

variable "enable_nat_gateway" {
  description = "Whether to create a NAT gateway for private subnet internet access"
  type        = bool
}

variable "tags" {
  description = "Common tags to apply to all resources"
  type        = map(string)
}

# ------------------------------------------------------------------------------
# VPC Flow Logs
# ------------------------------------------------------------------------------

variable "enable_flow_logs" {
  description = "Enable VPC flow logs"
  type        = bool
}

variable "log_retention_days" {
  description = "CloudWatch log retention in days for VPC flow logs"
  type        = number
}

# ------------------------------------------------------------------------------
# Portal east-west inspection (#122)
# ------------------------------------------------------------------------------

variable "enable_portal_inspection" {
  description = "Insert an AWS Network Firewall east-west inspection boundary between the portal public (ALB) tier and the private (Django / RDS / Redis / Guacamole) tier."
  type        = bool
}

variable "portal_inspection_delete_protection" {
  description = "Enable delete protection on the portal inspection AWS Network Firewall. Mirrors the `enable_deletion_protection` (ALB) / `db_deletion_protection` (RDS) convention: secure default is `true` in prod; dev environments that need intentional teardown set this to `false` and re-apply before destroying. This is a Terraform lifecycle setting only — it governs whether Terraform may delete the firewall and does not change inspection, routing, or logging."
  type        = bool
  default     = true
}

variable "enable_log_aggregation" {
  description = "Whether the env root's log aggregation pipeline is enabled. Used only to fail closed: enable_portal_inspection requires enable_log_aggregation = true so firewall FLOW / ALERT logs reach the existing pipeline instead of dead-ending in CloudWatch."
  type        = bool
}

variable "firewall_log_retention_days" {
  description = "CloudWatch retention in days for Network Firewall FLOW / ALERT logs."
  type        = number
}

variable "firewall_subnet_cidr" {
  description = "CIDR block for the dedicated portal inspection firewall subnet. Must not overlap with the public, private, public-workload, or other reserved subnets in vpc_cidr. Default places it at the top of the VPC /16 to avoid collision with the public/private/public-workload /20 tiers."
  type        = string
  default     = ""
}

variable "permissions_boundary_arn" {
  description = "Permissions boundary ARN required on CI-created shifter-* roles"
  type        = string
}
