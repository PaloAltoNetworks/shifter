# GCP dev environment variables

variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "region" {
  description = "GCP region"
  type        = string
  default     = "us-central1"
}

variable "environment" {
  description = "Environment name"
  type        = string
  default     = "dev"
}

# ------------------------------------------------------------------------------
# Network CIDRs
# ------------------------------------------------------------------------------

variable "gke_subnet_cidr" {
  description = "Primary CIDR for GKE node IPs"
  type        = string
  default     = "10.0.0.0/20"
}

variable "gke_pods_cidr" {
  description = "Secondary CIDR for GKE pod IPs"
  type        = string
  default     = "10.4.0.0/14"
}

variable "gke_services_cidr" {
  description = "Secondary CIDR for GKE service IPs"
  type        = string
  default     = "10.8.0.0/20"
}

# ------------------------------------------------------------------------------
# Optional features
# ------------------------------------------------------------------------------

variable "enable_flow_logs" {
  description = "Enable VPC flow logs"
  type        = bool
  default     = false
}

variable "labels" {
  description = "Labels to apply to all resources"
  type        = map(string)
  default     = {}
}
