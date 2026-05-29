# VPC module variables - NO DEFAULTS

variable "name_prefix" {
  description = "Prefix for resource names (e.g., prod-portal)"
  type        = string
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC"
  type        = string
}

variable "az_count" {
  description = "Number of availability zones to use"
  type        = number
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

variable "enable_log_aggregation" {
  description = "Whether the env root's log aggregation pipeline is enabled. Used only to fail closed: enable_portal_inspection requires enable_log_aggregation = true so firewall FLOW / ALERT logs reach the existing pipeline instead of dead-ending in CloudWatch."
  type        = bool
}

variable "firewall_log_retention_days" {
  description = "CloudWatch retention in days for Network Firewall FLOW / ALERT logs."
  type        = number
}

variable "firewall_subnet_cidr" {
  description = "CIDR block for the dedicated portal inspection firewall subnet. Must not overlap with public, private, or other reserved subnets in vpc_cidr. Default places it at the top of the VPC /16 to avoid collision with the public/private /20 tiers."
  type        = string
  default     = ""
}
