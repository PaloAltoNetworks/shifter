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

variable "environment" {
  description = "Environment name (dev, staging, prod)"
  type        = string
  default     = "dev"
}

variable "secrets_kms_key_arn" {
  description = "ARN of the portal Secrets Manager CMK used to encrypt range instance SSH-key secrets at runtime (CKV_AWS_149). Sourced from the engine-provisioner ECS task env (SECRETS_KMS_KEY_ARN) which is wired from the platform env root."
  type        = string
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
