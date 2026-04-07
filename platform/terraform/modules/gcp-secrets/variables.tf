variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "name_prefix" {
  description = "Prefix for resource names"
  type        = string
}

variable "portal_service_account_email" {
  description = "Portal Kubernetes SA email (for secret access). Empty to skip IAM bindings."
  type        = string
  default     = ""
}

variable "labels" {
  description = "Labels to apply"
  type        = map(string)
  default     = {}
}
