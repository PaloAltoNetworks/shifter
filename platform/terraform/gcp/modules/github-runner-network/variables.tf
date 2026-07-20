variable "project_id" {
  type        = string
  description = "GCP project the runner network is created in (the dev tenant's own project)."
}

variable "region" {
  type        = string
  description = "GCP region for the runner subnet, router, and NAT."
}

variable "name_prefix" {
  type        = string
  description = "Resource name prefix (e.g. shifter-gcp-dev)."
}

variable "runner_subnet_cidr" {
  type        = string
  description = "RFC1918 CIDR for the dedicated runner subnet. Must not overlap the platform or range networks."
}

variable "runner_service_account_email" {
  type        = string
  description = "Email of the runner VM service account the IAP SSH firewall rule targets."
}
