variable "project_id" {
  type        = string
  description = "GCP project to provision the runner into (the dev tenant's own project). Supplied at apply time, never committed."
}

variable "environment" {
  type        = string
  description = "Environment name (e.g. gcp-dev). Used for resource naming and labels."
}

variable "region" {
  type        = string
  description = "GCP region for the runner network, router, and NAT."
}

variable "zone" {
  type        = string
  description = "GCP compute zone for the runner instance(s)."
}

variable "runner_count" {
  type        = number
  default     = 1
  description = "Number of runner instances to provision."

  validation {
    condition     = var.runner_count > 0
    error_message = "runner_count must be a positive integer."
  }
}

variable "machine_type" {
  type        = string
  default     = "e2-standard-4"
  description = "GCE machine type for the runner instance(s)."
}

variable "runner_image" {
  type        = string
  default     = "projects/ubuntu-os-cloud/global/images/family/ubuntu-2204-lts"
  description = "Base image for the runner instance. Pinned to an immutable family, not 'latest'."
}

variable "runner_disk_size_gb" {
  type        = number
  default     = 100
  description = "Boot disk size (GB) for the runner instance(s)."
}

variable "runner_version" {
  type        = string
  description = "Pinned GitHub Actions runner version to install (immutable; no 'latest')."
}

variable "runner_checksum" {
  type        = string
  description = "SHA-256 checksum of the linux-x64 Actions runner tarball for the pinned version. The startup script fails closed on mismatch."
}

variable "runner_user" {
  type        = string
  default     = "runner"
  description = "Dedicated unprivileged OS user the runner binary/service run as."
}

variable "runner_subnet_cidr" {
  type        = string
  default     = "10.200.0.0/24"
  description = "RFC1918 CIDR for the dedicated runner subnet. Must not overlap the platform or range networks."
}

# No create_runner_network / runner_subnet_self_link opt-out: the dedicated
# custom VPC is mandatory (ADR-008-R8), so the runner can never be placed on a
# default or shared network. See main.tf's module "runner_network".
