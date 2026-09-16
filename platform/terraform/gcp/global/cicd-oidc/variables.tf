variable "project_id" {
  description = "GCP project that hosts the Workload Identity pool and packer build service account."
  type        = string
}

variable "environment" {
  description = "Environment name (e.g. gcp-dev)."
  type        = string
}

variable "region" {
  description = "Default provider region."
  type        = string
  default     = "us-central1"
}

variable "github_org" {
  description = "GitHub organization that owns the repository allowed to federate."
  type        = string
  default     = "Brad-Edwards"
}

variable "github_repo" {
  description = "GitHub repository allowed to federate into the build service account."
  type        = string
  default     = "shifter"
}

variable "promotion_reader_service_account_email" {
  description = "Prod promote SA email granted read-only access to images when this is the source-project root."
  type        = string
  default     = ""
}

variable "build_read_bucket_names" {
  description = "Existing GCS input buckets readable by the Packer build identity."
  type        = set(string)
  default     = []
}

variable "terraform_state_bucket_name" {
  description = "Explicit deployment-owned GCS backend bucket receiving scoped deploy/destroy access."
  type        = string
  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$", var.terraform_state_bucket_name))
    error_message = "terraform_state_bucket_name must name the separately owned platform state bucket."
  }
}

variable "platform_external_bucket_names" {
  description = "Existing RAES/CTF content buckets whose workload IAM is managed by platform-core."
  type        = set(string)
  default     = []
}

variable "github_subject_format" {
  description = "Reviewed GitHub default subject format: legacy names or immutable owner/repository IDs."
  type        = string
  default     = "default"
  validation {
    condition     = contains(["default", "immutable"], var.github_subject_format)
    error_message = "github_subject_format must be default or immutable."
  }
}
