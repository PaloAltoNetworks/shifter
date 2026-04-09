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

# Network configuration
variable "vpc_id" {
  description = "Range VPC/network identifier. On GCP this is the network self_link or name."
  type        = string
}

variable "vpc_cidr" {
  description = "Range network CIDR block reserved for range allocation."
  type        = string
}

variable "availability_zone" {
  description = "Zone for all range instances (for example us-central1-b)."
  type        = string
}

variable "region" {
  description = "Optional explicit region for subnet resources. Defaults to the region derived from availability_zone."
  type        = string
  default     = ""
}

# Network integration
variable "portal_vpc_cidr" {
  description = "Legacy single portal CIDR for SSH/RDP access."
  type        = string
  default     = ""
}

variable "portal_network_cidrs" {
  description = "Optional list of portal-side CIDRs for SSH/RDP access."
  type        = list(string)
  default     = []
}

variable "portal_vpc_peering_id" {
  description = "Unused on GCP range module. Present for cross-provider compatibility."
  type        = string
  default     = ""
}

variable "s3_endpoint_id" {
  description = "Unused on GCP range module. Present for cross-provider compatibility."
  type        = string
  default     = ""
}

variable "firewall_endpoint_id" {
  description = "Unused on GCP range module. Present for cross-provider compatibility."
  type        = string
  default     = ""
}

variable "ngfw_data_eni_id" {
  description = "Unused on GCP range module. Present for future cross-provider compatibility."
  type        = string
  default     = ""
}

# Image identifiers
variable "kali_ami_id" {
  description = "Image reference for Kali attacker instances."
  type        = string
}

variable "victim_ami_id" {
  description = "Image reference for Linux victim instances."
  type        = string
}

variable "windows_ami_id" {
  description = "Image reference for Windows victim instances."
  type        = string
}

variable "dc_ami_id" {
  description = "Image reference for Domain Controller instances."
  type        = string
}

# Instance configuration
variable "instance_profile_name" {
  description = "Unused on GCP range module. Present for cross-provider compatibility."
  type        = string
  default     = ""
}

variable "service_account_email" {
  description = "Optional service account email for range instances."
  type        = string
  default     = ""
}

variable "service_account_scopes" {
  description = "OAuth scopes for the optional service account attached to range instances."
  type        = list(string)
  default     = ["https://www.googleapis.com/auth/cloud-platform"]
}

variable "boot_disk_size_gb" {
  description = "Boot disk size in GiB for guest instances."
  type        = number
  default     = 50
}

variable "boot_disk_type" {
  description = "Boot disk type for guest instances."
  type        = string
  default     = "pd-balanced"
}

variable "windows_admin_password" {
  description = "Local Administrator password injected by the Windows startup scripts."
  type        = string
  default     = "CortexSavesTheDay!"
  sensitive   = true
}

# Subnets specification (JSON from Python)
variable "subnets" {
  description = "List of subnet configurations with pre-allocated CIDRs"
  type = list(object({
    name         = string
    uuid         = string
    cidr         = string
    connected_to = list(string)
    instances = list(object({
      uuid                = string
      name                = string
      role                = string
      os_type             = string
      instance_type       = string
      agent_presigned_url = string
      join_domain         = bool
      ami_id              = string
    }))
  }))
}
