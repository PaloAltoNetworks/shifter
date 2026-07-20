variable "project_id" {
  type = string
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
  type = number
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
