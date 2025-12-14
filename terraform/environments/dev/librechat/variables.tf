# LibreChat Environment Variables

# ------------------------------------------------------------------------------
# General
# ------------------------------------------------------------------------------

variable "environment" {
  description = "Environment name (e.g., prod, dev)"
  type        = string
}

variable "aws_region" {
  description = "AWS region"
  type        = string
}

variable "tags" {
  description = "Common tags to apply to all resources"
  type        = map(string)
}

# ------------------------------------------------------------------------------
# LibreChat
# ------------------------------------------------------------------------------

variable "subnet_cidr" {
  description = "CIDR block for LibreChat subnet"
  type        = string
}

variable "instance_type" {
  description = "EC2 instance type for LibreChat"
  type        = string
  default     = "t3.micro"
}

variable "root_volume_size" {
  description = "Size of root EBS volume in GB"
  type        = number
  default     = 20
}

variable "data_volume_size" {
  description = "Size of data EBS volume for MongoDB in GB"
  type        = number
  default     = 20
}

variable "app_title" {
  description = "LibreChat application title"
  type        = string
  default     = "Shifter Chat (Dev)"
}

variable "allow_registration" {
  description = "Allow new user registration (set false after admin created)"
  type        = bool
  default     = true
}
