variable "project_id" {
  type = string
}

variable "artifact_registry_location" {
  type = string
}

variable "release_scan_service_account_email" {
  description = "Purpose-scoped CI identity allowed to pull images for exact-digest scanning."
  type        = string
  default     = ""
}

variable "name_prefix" {
  type = string
}

variable "common_labels" {
  type = map(string)
}

variable "artifact_repositories" {
  type = set(string)
}

variable "environment" {
  type = string
}

variable "project_number" {
  type = number
}
