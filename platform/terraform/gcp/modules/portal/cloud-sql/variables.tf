variable "project_id" {
  type = string
}

variable "cloud_sql_iam_auth" {
  type        = bool
  default     = false
  description = "Enable the native IAM login flag for attached workload identities."
}

variable "openfga_enabled" {
  type        = bool
  default     = false
  description = "Create a dedicated policy database on the supported shared instance."
  validation {
    condition     = !var.openfga_enabled || (var.cloud_sql_iam_auth && var.cloud_sql_database_name != "openfga")
    error_message = "The native policy datastore requires IAM login and a distinct application database."
  }
}

variable "region" {
  type = string
}

variable "name_prefix" {
  type = string
}

variable "common_labels" {
  type = map(string)
}

variable "platform_network_id" {
  type = string
}

variable "cloud_sql_database_version" {
  type = string
}

variable "cloud_sql_tier" {
  type = string
}

variable "cloud_sql_availability_type" {
  type = string
}

variable "cloud_sql_disk_size_gb" {
  description = "Minimum Cloud SQL disk size in GiB; provider storage does not shrink."
  type        = number
}

variable "cloud_sql_database_name" {
  type = string
}

variable "cloud_sql_user_name" {
  type = string
}

variable "cloud_sql_deletion_protection" {
  type = bool
}
