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

variable "admin_password" {
  description = "Windows Administrator password"
  type        = string
  sensitive   = true
}

variable "allowed_rdp_cidrs" {
  description = "CIDR blocks allowed to RDP (use your IP). Leave empty to use SSM only."
  type        = list(string)
}
