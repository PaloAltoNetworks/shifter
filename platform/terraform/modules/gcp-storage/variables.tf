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

variable "gke_node_service_account_email" {
  description = "GKE node SA email (read access to bucket)"
  type        = string
}

variable "cicd_service_account_email" {
  description = "CI/CD SA email (write access). Empty to skip."
  type        = string
  default     = ""
}

variable "labels" {
  description = "Labels to apply"
  type        = map(string)
  default     = {}
}
