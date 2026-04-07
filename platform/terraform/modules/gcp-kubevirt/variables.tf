# KubeVirt module variables

variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "region" {
  description = "GCP region (for Artifact Registry)"
  type        = string
  default     = "us-central1"
}

variable "name_prefix" {
  description = "Prefix for resource names (e.g., dev-range)"
  type        = string
}

# ------------------------------------------------------------------------------
# Operator versions (pinned for reproducibility)
# ------------------------------------------------------------------------------

variable "kubevirt_version" {
  description = "KubeVirt release version (check https://github.com/kubevirt/kubevirt/releases)"
  type        = string
  default     = "v1.4.0"
}

variable "cdi_version" {
  description = "CDI release version (check https://github.com/kubevirt/containerized-data-importer/releases)"
  type        = string
  default     = "v1.60.3"
}

# ------------------------------------------------------------------------------
# GKE integration
# ------------------------------------------------------------------------------

variable "gke_node_service_account_email" {
  description = "GKE node service account email (for Artifact Registry pull access)"
  type        = string
}

variable "cicd_service_account_email" {
  description = "CI/CD service account email (for Artifact Registry push access). Empty to skip."
  type        = string
  default     = ""
}

variable "storage_class" {
  description = "Kubernetes StorageClass for CDI scratch space (pd-ssd recommended)"
  type        = string
  default     = "premium-rwo"
}

# ------------------------------------------------------------------------------
# Labels
# ------------------------------------------------------------------------------

variable "labels" {
  description = "Labels to apply to GCP resources"
  type        = map(string)
  default     = {}
}
