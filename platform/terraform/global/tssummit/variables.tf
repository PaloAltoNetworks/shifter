variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-2"
}

variable "ami_id" {
  description = "AMI ID for WebServer1 (migrated from original instance)"
  type        = string
}

variable "instance_type" {
  description = "EC2 instance type"
  type        = string
  default     = "t3.micro"
}

variable "key_name" {
  description = "SSH key pair name"
  type        = string
  default     = "tssummitwebserver"
}

variable "subnet_id" {
  description = "Subnet ID in the default VPC"
  type        = string
}

variable "ssh_allowed_cidrs" {
  description = "Map of description to CIDR for SSH ingress rules"
  type        = map(string)
}

variable "ctfd_ami_id" {
  description = "AMI ID for the CTFd instance"
  type        = string
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

variable "ngfw_server_subnet_id" {
  description = "Existing dev-server subnet ID for NGFW server interface"
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
# Workstation Variables
# ------------------------------------------------------------------------------

variable "workstation_ami_id" {
  description = "AMI ID for the workstation (Windows Server 2025 Desktop Experience)"
  type        = string
}

variable "workstation_instance_type" {
  description = "Workstation EC2 instance type"
  type        = string
  default     = "t3.medium"
}

# ------------------------------------------------------------------------------
# Windows Instance Variables
# ------------------------------------------------------------------------------

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
