variable "workload_identity_pool" {
  type        = string
  description = "Workload Identity pool from the GKE cluster resource, ordering bindings after pool creation."
}

variable "project_id" {
  type = string
}

variable "cloud_sql_iam_auth" {
  type        = bool
  default     = false
  description = "Register native database users and instance-scoped connector/login authority."
}

variable "cloud_sql_instance_name" {
  type        = string
  default     = ""
  description = "Instance from the owning Cloud SQL module; never an independently selected target."
  validation {
    condition     = !var.cloud_sql_iam_auth || can(regex("^[a-z][a-z0-9-]{0,97}$", var.cloud_sql_instance_name))
    error_message = "Native SQL authentication requires the owning instance name."
  }
}

variable "openfga_enabled" {
  type        = bool
  default     = false
  description = "Create separate native runtime, API administration and schema migration identities."
  validation {
    condition     = !var.openfga_enabled || var.cloud_sql_iam_auth
    error_message = "The native policy datastore requires Cloud SQL IAM authentication."
  }
}

variable "dynamic_secret_project_id" {
  type        = string
  description = "Deployment-scoped project that owns provisioner-created range secrets."
}

variable "provisioner_static_secret_ids" {
  type        = set(string)
  default     = []
  description = "Exact operator-created Secret Manager resources read by the provisioner outside the dynamic boundary."
}

variable "environment" {
  type = string
}

variable "name_prefix" {
  type = string
}

variable "range_host_identity_pool_size" {
  type        = number
  default     = 0
  description = "Number of pre-created service accounts available to preconfigured range hosts."

  validation {
    condition = (
      var.range_host_identity_pool_size >= 0
      && floor(var.range_host_identity_pool_size) == var.range_host_identity_pool_size
    )
    error_message = "range_host_identity_pool_size must be a non-negative integer."
  }
}

# ADR-008-R7: resource IDs handed in from the owning modules (portal/secrets,
# portal/gcs, platform-core) so Secret Manager and Cloud Storage access can be
# bound per named resource instead of at project scope. No secret inventory or
# bucket-name convention is duplicated here.

variable "runtime_secret_ids" {
  type        = map(string)
  description = "Secret Manager secret resource IDs keyed by runtime bundle name (from module.portal_secrets.runtime_secret_ids)."
}

variable "feature_artifact_prefix" {
  type        = string
  default     = "raes/content-delivery"
  description = "Content-addressed delivery prefix (runtime RAES_CONTENT_DELIVERY_PREFIX) on the assets bucket that feature-artifact acquisition writes and verification reads."
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

variable "raes_package_bucket_name" {
  type        = string
  default     = ""
  description = "Optional GCS bucket holding object-backed RAES package archives (#1567). Grants the portal objectUser access for verified reads, tenant uploads and failed-upload cleanup. Empty disables the binding."
}

variable "ctf_content_bucket_name" {
  type        = string
  default     = ""
  description = "Optional private GCS bucket holding digest-pinned native CTF content bundles. Grants the portal read-only access. Empty disables the binding."
}

variable "deploy_service_account_email" {
  type        = string
  default     = ""
  description = <<-EOT
    Email of the CI deploy service account (the purpose-scoped WIF SA in
    global/cicd-oidc) that runs `terraform apply` for this stack. Granted
    resource-scoped roles/iam.serviceAccountUser on the GKE node SA so it can
    create the node pools that run as that node SA (actAs). Scoped, not project-
    wide, to satisfy CKV_GCP_41. Empty disables the binding (e.g. when the stack
    is applied by an operator identity that already holds broad actAs).
  EOT
}
