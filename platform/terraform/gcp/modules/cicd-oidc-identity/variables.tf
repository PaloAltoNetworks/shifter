variable "project_id" {
  description = "GCP project that hosts this environment's WIF provider and purpose identities."
  type        = string
}

variable "environment" {
  description = "Deployment ID, independent of installation profile and purpose."
  type        = string
  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{0,38}[a-z0-9]$", var.environment))
    error_message = "environment must be a DNS-label-safe deployment ID."
  }
}

variable "name_prefix" {
  description = "Resource name prefix (for example shifter-gcp-dev)."
  type        = string
}

variable "region" {
  description = "Region for the private release-evidence bucket."
  type        = string
}

variable "github_org" {
  description = "GitHub organization that owns the repository allowed to federate."
  type        = string
  default     = "Brad-Edwards"
}

variable "github_repo" {
  description = "GitHub repository allowed to federate into the purpose identities."
  type        = string
  default     = "shifter"
}

variable "build_roles" {
  description = "Predefined roles exercised by the Packer build/export identity."
  type        = list(string)
  default = [
    "roles/compute.instanceAdmin.v1",
    "roles/compute.storageAdmin",
    "roles/iap.tunnelResourceAccessor",
    "roles/cloudbuild.builds.editor",
  ]
}

variable "build_read_bucket_names" {
  description = "Existing input buckets the Packer build identity may read, such as the Polaris stack bucket."
  type        = set(string)
  default     = []
}

variable "validate_roles" {
  description = "Predefined roles exercised by the no-SA validation VM path."
  type        = list(string)
  default = [
    "roles/iap.tunnelResourceAccessor",
  ]
}

variable "validate_permissions" {
  description = "Custom-role permissions for exact-candidate validation."
  type        = list(string)
  default = [
    "compute.disks.create",
    "compute.disks.delete",
    "compute.disks.get",
    "compute.disks.use",
    "compute.disks.useReadOnly",
    "compute.images.get",
    "compute.images.getFromFamily",
    "compute.images.setLabels",
    "compute.images.useReadOnly",
    "compute.instances.create",
    "compute.instances.delete",
    "compute.instances.attachDisk",
    "compute.instances.get",
    "compute.instances.reset",
    "compute.instances.setTags",
    "compute.machineTypes.get",
    "compute.networks.get",
    "compute.networks.use",
    "compute.subnetworks.get",
    "compute.subnetworks.use",
    "compute.zoneOperations.get",
    "compute.zones.get",
    "resourcemanager.projects.get",
    "serviceusage.services.use",
  ]
}

variable "promote_permissions" {
  description = "Custom-role permissions for prod image copy and verified family commit."
  type        = list(string)
  default = [
    "compute.globalOperations.get",
    "compute.images.create",
    "compute.images.deprecate",
    "compute.images.get",
    "compute.images.getFromFamily",
    "compute.images.list",
    "compute.images.setLabels",
    "compute.images.update",
    "compute.images.useReadOnly",
    "resourcemanager.projects.get",
    "serviceusage.services.use",
  ]
}

variable "deploy_roles" {
  description = "Platform-core roles granted only to the deploy identity."
  type        = list(string)
  default = [
    "roles/compute.networkAdmin",
    "roles/compute.securityAdmin",
    "roles/gkehub.editor",
    "roles/gkehub.gatewayEditor",
    "roles/gkehub.viewer",
    "roles/container.admin",
    "roles/serviceusage.serviceUsageAdmin",
    "roles/servicenetworking.networksAdmin",
    "roles/dns.admin",
    "roles/cloudsql.admin",
    "roles/redis.admin",
    "roles/pubsub.admin",
    "roles/secretmanager.admin",
    "roles/cloudkms.admin",
    "roles/artifactregistry.admin",
    "roles/identityplatform.admin",
    "roles/monitoring.editor",
    "roles/iam.serviceAccountAdmin",
    "roles/resourcemanager.projectIamAdmin",
  ]
}

variable "destroy_roles" {
  description = "Platform-core teardown roles granted only to the destroy identity."
  type        = list(string)
  default = [
    "roles/compute.networkAdmin",
    "roles/compute.securityAdmin",
    "roles/gkehub.editor",
    "roles/gkehub.gatewayEditor",
    "roles/gkehub.viewer",
    "roles/container.admin",
    "roles/servicenetworking.networksAdmin",
    "roles/dns.admin",
    "roles/cloudsql.admin",
    "roles/redis.admin",
    "roles/pubsub.admin",
    "roles/secretmanager.admin",
    "roles/cloudkms.admin",
    "roles/artifactregistry.admin",
    "roles/identityplatform.admin",
    "roles/monitoring.editor",
    "roles/iam.serviceAccountAdmin",
    "roles/resourcemanager.projectIamAdmin",
  ]
}

variable "deploy_storage_permissions" {
  description = "Storage permissions for Terraform-managed platform buckets, bound only to their deterministic resource names."
  type        = list(string)
  default = [
    "storage.buckets.create",
    "storage.buckets.delete",
    "storage.buckets.get",
    "storage.buckets.getIamPolicy",
    "storage.buckets.setIamPolicy",
    "storage.buckets.update",
    "storage.objects.create",
    "storage.objects.delete",
    "storage.objects.get",
    "storage.objects.list",
    "storage.objects.update",
  ]
}

variable "destroy_storage_permissions" {
  description = "Storage permissions needed to tear down Terraform-managed platform buckets, bound only to their deterministic resource names."
  type        = list(string)
  default = [
    "storage.buckets.delete",
    "storage.buckets.get",
    "storage.buckets.getIamPolicy",
    "storage.buckets.setIamPolicy",
    "storage.objects.delete",
    "storage.objects.get",
    "storage.objects.list",
  ]
}

variable "promotion_reader_service_account_email" {
  description = "Prod promote SA email granted read-only access to source images by the source-project root."
  type        = string
  default     = ""

  validation {
    condition = var.promotion_reader_service_account_email == "" || can(regex(
      "^[a-z][a-z0-9-]{4,28}[a-z0-9]@[a-z][a-z0-9-]{4,28}[a-z0-9]\\.iam\\.gserviceaccount\\.com$",
      var.promotion_reader_service_account_email,
    ))
    error_message = "promotion_reader_service_account_email must be empty or a service-account email."
  }
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
  description = "Existing content buckets whose IAM memberships are managed by platform-core; each receives exact bucket-level lifecycle IAM administration."
  type        = set(string)
  default     = []

  validation {
    condition = alltrue([
      for name in var.platform_external_bucket_names :
      length(trimspace(name)) > 0 && lower(name) != lower(var.release_evidence_bucket_name)
    ])
    error_message = "platform_external_bucket_names must contain non-empty names and must not include this identity root's release-evidence bucket."
  }
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
