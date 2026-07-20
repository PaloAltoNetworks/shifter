variable "project_id" {
  type = string
}

variable "environment" {
  type = string
}

variable "name_prefix" {
  type = string
}

# ADR-008-R7: resource IDs handed in from the owning modules (portal/secrets,
# portal/gcs, platform-core) so Secret Manager and Cloud Storage access can be
# bound per named resource instead of at project scope. No secret inventory or
# bucket-name convention is duplicated here.

variable "runtime_secret_ids" {
  type        = map(string)
  description = "Secret Manager secret resource IDs keyed by runtime bundle name (from module.portal_secrets.runtime_secret_ids)."
}

variable "assets_bucket_name" {
  type        = string
  description = "Name of the shared platform assets GCS bucket (from module.portal_gcs.assets_bucket_name)."
}

variable "terraform_state_bucket_name" {
  type        = string
  description = "Name of the GCS bucket holding per-range Terraform/Pulumi state (bootstrapped out of band)."

  validation {
    condition     = length(trimspace(var.terraform_state_bucket_name)) > 0
    error_message = "terraform_state_bucket_name must be a non-empty bucket name."
  }
}

variable "vmseries_bootstrap_bucket_name" {
  type        = string
  default     = ""
  description = "Optional GCS bucket the provisioner writes VM-Series bootstrap ISOs to. Empty disables the binding."
}

variable "aces_package_bucket_name" {
  type        = string
  default     = ""
  description = "Optional GCS bucket holding object-backed ACES package archives (#1567). Grants the portal read-only (objectViewer) access. Empty disables the binding."
}
