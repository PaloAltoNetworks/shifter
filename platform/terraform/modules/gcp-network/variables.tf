# GCP Network module variables

variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "region" {
  description = "GCP region"
  type        = string
  default     = "us-central1"
}

variable "name_prefix" {
  description = "Prefix for resource names (e.g., dev-range)"
  type        = string
}

# ------------------------------------------------------------------------------
# GKE Subnet CIDRs
# ------------------------------------------------------------------------------

variable "gke_subnet_cidr" {
  description = "Primary CIDR for GKE node IPs"
  type        = string
  default     = "10.0.0.0/20"
}

variable "gke_pods_cidr" {
  description = "Secondary CIDR for GKE pod IPs (KubeVirt VMs get IPs from here)"
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
  description = "Enable VPC flow logs on the GKE subnet"
  type        = bool
  default     = false
}

variable "enable_nat_logging" {
  description = "Enable Cloud NAT logging"
  type        = bool
  default     = true
}

variable "labels" {
  description = "Labels to apply to all resources"
  type        = map(string)
  default     = {}
}
