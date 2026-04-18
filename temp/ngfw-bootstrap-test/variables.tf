variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-2"
}

variable "aws_profile" {
  description = "AWS CLI profile"
  type        = string
  default     = "panw-shifter-dev-workstation"
}

variable "vm_series_ami_id" {
  description = "VM-Series AMI ID"
  type        = string
  # PAN-OS 11.2.8 BYOL in us-east-2 (same as dev environment)
  default = "ami-065e27477b191614c"
}

variable "instance_type" {
  description = "EC2 instance type"
  type        = string
  default     = "m5.xlarge"
}

variable "scm_pin_id" {
  description = "SCM auto-registration PIN ID"
  type        = string
  default     = ""
}

variable "scm_pin_value" {
  description = "SCM auto-registration PIN value"
  type        = string
  default     = ""
  sensitive   = true
}

variable "scm_folder_name" {
  description = "SCM folder name (dgname)"
  type        = string
  default     = ""
}

variable "authcode" {
  description = "VM-Series authcode for licensing"
  type        = string
  default     = ""
  sensitive   = true
}

variable "admin_password_hash" {
  description = "PAN-OS password hash for admin user (generate with: openssl passwd -1 -salt <salt> <password>)"
  type        = string
  # Default: password is "admin" with salt "shifter"
  # Generate your own: openssl passwd -1 -salt shifter yourpassword
  default = "$1$shifter$RjIyb38T1W1gzBTjOFzyH0"
  sensitive = true
}
