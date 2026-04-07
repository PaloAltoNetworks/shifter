variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "region" {
  description = "GCP region"
  type        = string
}

variable "name_prefix" {
  description = "Prefix for resource names"
  type        = string
}

# ------------------------------------------------------------------------------
# Network
# ------------------------------------------------------------------------------

variable "network_id" {
  description = "VPC network self-link (for Private Services Access)"
  type        = string
}

# ------------------------------------------------------------------------------
# Database configuration
# ------------------------------------------------------------------------------

variable "database_version" {
  description = "Cloud SQL PostgreSQL version"
  type        = string
  default     = "POSTGRES_16"
}

variable "tier" {
  description = "Cloud SQL machine tier (e.g., db-custom-2-7680 for 2 vCPU, 7.5GB RAM)"
  type        = string
  default     = "db-custom-2-7680"
}

variable "availability_type" {
  description = "REGIONAL for HA (multi-zone), ZONAL for single-zone"
  type        = string
  default     = "ZONAL"
}

variable "disk_size_gb" {
  description = "Initial disk size in GB (auto-resizes)"
  type        = number
  default     = 20
}

variable "db_name" {
  description = "Name of the database to create"
  type        = string
  default     = "shifter"
}

variable "db_username" {
  description = "Database admin username"
  type        = string
  default     = "shifter"
}

# ------------------------------------------------------------------------------
# Backup and maintenance
# ------------------------------------------------------------------------------

variable "backup_retention_days" {
  description = "Number of days to retain backups"
  type        = number
  default     = 7
}

variable "enable_point_in_time_recovery" {
  description = "Enable point-in-time recovery (requires retained transaction logs)"
  type        = bool
  default     = true
}

variable "deletion_protection" {
  description = "Prevent accidental instance deletion"
  type        = bool
  default     = true
}

# ------------------------------------------------------------------------------
# IAM
# ------------------------------------------------------------------------------

variable "provisioner_service_account_email" {
  description = "Provisioner K8s SA email for IAM database auth. Empty to skip."
  type        = string
  default     = ""
}

# ------------------------------------------------------------------------------
# Labels
# ------------------------------------------------------------------------------

variable "labels" {
  description = "Labels to apply"
  type        = map(string)
  default     = {}
}
