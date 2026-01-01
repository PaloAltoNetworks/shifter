variable "aws_region" {
  description = "AWS region"
  type        = string
}

variable "instance_type" {
  description = "EC2 instance type - needs enough RAM for Cursor, Claude Code, etc"
  type        = string
}

variable "root_volume_size" {
  description = "Root volume size in GB"
  type        = number
}

variable "allowed_rdp_cidrs" {
  description = "CIDR blocks allowed to RDP (use your IP). Leave empty to use SSM only."
  type        = list(string)
}

# Optional: Portal VPC integration for direct DB access
variable "use_portal_vpc" {
  description = "Deploy in portal VPC instead of default VPC for direct DB access"
  type        = bool
  default     = false
}

variable "portal_vpc_id" {
  description = "Portal VPC ID (required if use_portal_vpc is true)"
  type        = string
  default     = ""
}

variable "portal_subnet_id" {
  description = "Portal subnet ID to deploy in (required if use_portal_vpc is true)"
  type        = string
  default     = ""
}

variable "portal_db_security_group_id" {
  description = "Portal RDS security group ID to allow DB access (optional)"
  type        = string
  default     = ""
}
