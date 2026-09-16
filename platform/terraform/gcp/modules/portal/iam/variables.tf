variable "project_id" {
  type = string
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

# ADR-008-R7: size of the pre-provisioned OpenVPN gateway service-account pool
# (sh-vpn-pool-0 .. N-1). Bounds concurrent OpenVPN ranges and must match
# VPN_GATEWAY_POOL_SIZE in the engine runtime env, which reserves slots into it.
variable "vpn_gateway_pool_size" {
  type    = number
  default = 24

  validation {
    condition     = var.vpn_gateway_pool_size >= 0 && floor(var.vpn_gateway_pool_size) == var.vpn_gateway_pool_size
    error_message = "vpn_gateway_pool_size must be a non-negative integer."
  }
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
  description = "Optional GCS bucket holding object-backed RAES package archives (#1567). Grants the portal read-only (objectViewer) access. Empty disables the binding."
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
