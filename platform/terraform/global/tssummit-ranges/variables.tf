variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-2"
}

variable "team_name" {
  description = "Team identifier (e.g. Team2, Team3)"
  type        = string
}

# ------------------------------------------------------------------------------
# Subnet CIDRs (must be unique per team, within 172.31.0.0/16)
# ------------------------------------------------------------------------------

variable "server_subnet_cidr" {
  description = "CIDR block for the server subnet"
  type        = string
}

variable "untrust_subnet_cidr" {
  description = "CIDR block for the untrust subnet"
  type        = string
}

variable "management_subnet_cidr" {
  description = "CIDR block for the management subnet"
  type        = string
}

variable "endpoint_subnet_cidr" {
  description = "CIDR block for the endpoint subnet"
  type        = string
}

# ------------------------------------------------------------------------------
# SSH / Access
# ------------------------------------------------------------------------------

variable "key_name" {
  description = "SSH key pair name"
  type        = string
  default     = "tssummitwebserver"
}

variable "ssh_allowed_cidrs" {
  description = "Map of description to CIDR for SSH ingress rules"
  type        = map(string)
}

# ------------------------------------------------------------------------------
# NGFW Variables
# ------------------------------------------------------------------------------

variable "ngfw_ami_id" {
  description = "VM-Series AMI ID"
  type        = string
}

variable "ngfw_instance_type" {
  description = "NGFW EC2 instance type"
  type        = string
  default     = "m5.xlarge"
}

variable "ngfw_instance_profile" {
  description = "IAM instance profile for NGFW"
  type        = string
  default     = "dev-range-ngfw-instance"
}

variable "ngfw_bootstrap_bucket" {
  description = "S3 bucket for NGFW bootstrap files"
  type        = string
}

variable "ngfw_scm_pin_id" {
  description = "SCM auto-registration PIN ID (certid)"
  type        = string
}

variable "ngfw_scm_pin_value" {
  description = "SCM auto-registration PIN value (certsecret)"
  type        = string
  sensitive   = true
}

variable "ngfw_authcode" {
  description = "VM-Series license authcode"
  type        = string
  sensitive   = true
}

# ------------------------------------------------------------------------------
# Instance AMIs
# ------------------------------------------------------------------------------

variable "webserver_ami_id" {
  description = "AMI ID for the webserver instance"
  type        = string
}

variable "webserver_instance_type" {
  description = "Webserver EC2 instance type"
  type        = string
  default     = "t2.small"
}

variable "workstation_ami_id" {
  description = "AMI ID for the workstation (Windows Server 2025 Desktop Experience)"
  type        = string
}

variable "workstation_instance_type" {
  description = "Workstation EC2 instance type"
  type        = string
  default     = "t3.medium"
}

variable "windows_server_ami_id" {
  description = "AMI ID for the Windows Server instance"
  type        = string
}

variable "windows_server_instance_type" {
  description = "Windows Server EC2 instance type"
  type        = string
  default     = "t3.medium"
}

variable "windows_desktop_ami_id" {
  description = "AMI ID for the Windows Desktop instance"
  type        = string
}

variable "windows_desktop_instance_type" {
  description = "Windows Desktop EC2 instance type"
  type        = string
  default     = "t3.large"
}

# ------------------------------------------------------------------------------
# AI App Variables
# ------------------------------------------------------------------------------

variable "ai_app_subnet_cidr" {
  description = "CIDR block for the AI app subnet"
  type        = string
}

variable "ai_app_ami_id" {
  description = "AMI ID for the AI app instance"
  type        = string
}

variable "ai_app_instance_type" {
  description = "AI App EC2 instance type"
  type        = string
  default     = "g4dn.xlarge"
}

variable "ai_app_allowed_cidrs" {
  description = "Map of description to CIDR for AI app ingress (SSH + port 8000). Updated day-of with student IPs."
  type        = map(string)
  default     = {}
}
