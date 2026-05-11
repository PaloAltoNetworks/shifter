variable "name_prefix" {
  description = "Resource name prefix (e.g., ngfw-user-42)"
  type        = string
}

variable "user_id" {
  description = "Owner's Django user ID"
  type        = number
}

variable "instance_uuid" {
  description = "UUID of this NGFW instance (for tagging/correlation)"
  type        = string
}

variable "request_uuid" {
  description = "UUID of the provisioning request (for tagging/correlation)"
  type        = string
}

variable "subnet_id" {
  description = "Subnet ID for ENIs"
  type        = string
}

variable "mgmt_security_group_id" {
  description = "Security group ID for management ENI"
  type        = string
}

variable "data_security_group_id" {
  description = "Security group ID for data ENI"
  type        = string
}

variable "ami_id" {
  description = "VM-Series AMI ID"
  type        = string
}

variable "instance_type" {
  description = "EC2 instance type"
  type        = string
  default     = "m5.xlarge"
}

variable "bootstrap_bucket" {
  description = "S3 bucket for bootstrap files"
  type        = string
}

variable "scm_pin_id" {
  description = "SCM auto-registration PIN ID"
  type        = string
}

variable "scm_pin_value" {
  description = "SCM auto-registration PIN value"
  type        = string
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
  sensitive   = true
}

variable "environment" {
  description = "Environment name for tagging (dev, staging, prod)"
  type        = string
  default     = "dev"
}

variable "instance_profile_name" {
  description = "IAM instance profile name"
  type        = string
  default     = null
}

variable "secrets_kms_key_arn" {
  description = "ARN of the portal Secrets Manager CMK used to encrypt the NGFW SSH-key secret at runtime (CKV_AWS_149). Sourced from the engine-provisioner ECS task env (SECRETS_KMS_KEY_ARN) which is wired from the platform env root."
  type        = string
}
