# GKE module variables

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
# Network (from gcp-network module outputs)
# ------------------------------------------------------------------------------

variable "network_id" {
  description = "Self-link of the VPC network"
  type        = string
}

variable "gke_subnet_id" {
  description = "Self-link of the GKE subnet"
  type        = string
}

variable "gke_pods_range_name" {
  description = "Name of the secondary range for pods"
  type        = string
}

variable "gke_services_range_name" {
  description = "Name of the secondary range for services"
  type        = string
}

# ------------------------------------------------------------------------------
# Cluster settings
# ------------------------------------------------------------------------------

variable "master_cidr" {
  description = "CIDR for the GKE master (control plane) private network"
  type        = string
  default     = "172.16.0.0/28"
}

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
  default     = true
}

# ------------------------------------------------------------------------------
# System node pool (CoreDNS, KubeVirt operator, etc.)
# ------------------------------------------------------------------------------

variable "system_machine_type" {
  description = "Machine type for system node pool"
  type        = string
  default     = "e2-standard-4"
}

variable "system_node_count" {
  description = "Number of system nodes"
  type        = number
  default     = 2
}

# ------------------------------------------------------------------------------
# KubeVirt node pool (runs actual VMs)
# ------------------------------------------------------------------------------

variable "kubevirt_machine_type" {
  description = "Machine type for KubeVirt nodes (must support nested virt — use n2-standard-*)"
  type        = string
  default     = "n2-standard-16"
}

variable "kubevirt_node_count" {
  description = "Initial/minimum number of KubeVirt nodes (scale based on VM count: ~7 VMs per n2-standard-16)"
  type        = number
  default     = 3
}

variable "kubevirt_enable_autoscaling" {
  description = "Enable cluster autoscaler for the KubeVirt node pool (recommended for CTF events)"
  type        = bool
  default     = false
}

variable "kubevirt_max_node_count" {
  description = "Maximum KubeVirt nodes when autoscaling is enabled (~4-5 VMs per n2-standard-16 node)"
  type        = number
  default     = 200
}

variable "kubevirt_disk_size_gb" {
  description = "Boot disk size for KubeVirt nodes (needs room for VM disk images)"
  type        = number
  default     = 200
}

# ------------------------------------------------------------------------------
# Labels
# ------------------------------------------------------------------------------

variable "labels" {
  description = "Labels to apply to all resources"
  type        = map(string)
  default     = {}
}
