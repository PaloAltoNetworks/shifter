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

# ------------------------------------------------------------------------------
# GKE Cluster
# ------------------------------------------------------------------------------

variable "master_authorized_cidrs" {
  description = "CIDRs allowed to access the GKE API server"
  type = list(object({
    cidr = string
    name = string
  }))
  default = [
    {
      cidr = "0.0.0.0/0"
      name = "all"
    }
  ]
}

variable "deletion_protection" {
  description = "Prevent accidental cluster deletion"
  type        = bool
  default     = false
}

variable "kubevirt_machine_type" {
  description = "Machine type for KubeVirt nodes (must support nested virt — n2-standard-*)"
  type        = string
  default     = "n2-standard-16"
}

variable "kubevirt_node_count" {
  description = "Number of KubeVirt nodes (scale for events: ~7 VMs per n2-standard-16)"
  type        = number
  default     = 3
}

# ------------------------------------------------------------------------------
# Cloud SQL
# ------------------------------------------------------------------------------

variable "db_tier" {
  description = "Cloud SQL machine tier"
  type        = string
  default     = "db-custom-2-7680"
}

variable "db_availability_type" {
  description = "ZONAL (dev) or REGIONAL (prod HA)"
  type        = string
  default     = "ZONAL"
}

variable "redis_tier" {
  description = "BASIC (dev) or STANDARD_HA (prod)"
  type        = string
  default     = "BASIC"
}

variable "redis_memory_size_gb" {
  description = "Redis memory in GB"
  type        = number
  default     = 1
}

# ------------------------------------------------------------------------------
# KubeVirt + CDI
# ------------------------------------------------------------------------------

variable "kubevirt_version" {
  description = "KubeVirt release version"
  type        = string
  default     = "v1.4.0"
}

variable "cdi_version" {
  description = "CDI release version"
  type        = string
  default     = "v1.60.3"
}

variable "cicd_service_account_email" {
  description = "CI/CD service account email for Artifact Registry push access (from gcp-iam bootstrap)"
  type        = string
  default     = ""
}

# ------------------------------------------------------------------------------
# Labels
# ------------------------------------------------------------------------------

variable "labels" {
  description = "Labels to apply to all resources"
  type        = map(string)
  default     = {}
}
