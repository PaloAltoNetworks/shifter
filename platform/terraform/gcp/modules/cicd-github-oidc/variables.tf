variable "project_id" {
  description = "GCP project that hosts the Workload Identity pool and packer build service account."
  type        = string
}

variable "environment" {
  description = "Environment name (dev or prod)."
  type        = string
}

variable "name_prefix" {
  description = "Resource name prefix (e.g. shifter-gcp-dev)."
  type        = string
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

variable "labels" {
  description = "Resource labels."
  type        = map(string)
  default     = {}
}

variable "region" {
  description = "Region for the packer builder subnet and image bucket."
  type        = string
}

variable "platform_network" {
  description = "Name/self_link of the platform VPC network that hosts the packer builder subnet (has Cloud NAT for egress)."
  type        = string
}

variable "build_subnet_cidr" {
  description = "Primary CIDR for the dedicated packer builder subnet."
  type        = string
  default     = "172.16.8.0/28"
}

variable "image_bucket_location" {
  description = "Location for the GDC VM Runtime image bucket (GCE->GCS exports)."
  type        = string
  default     = "us-central1"
}

variable "image_reader_service_accounts" {
  description = "Service accounts granted read on the GDC VM image bucket (the GDC VM Runtime image-pull identity)."
  type        = list(string)
  default     = []
}

variable "allowed_workflow_refs" {
  description = <<-EOT
    GitHub refs whose OIDC tokens are accepted by the WIF provider. Tokens from
    any other ref are rejected at the provider before the SA binding is consulted
    (ADR-037-R7). Defaults to the two protected integration branches. Override
    only with explicit justification documented in docs/adr/exceptions.yaml.
  EOT
  type        = list(string)
  default     = ["refs/heads/dev", "refs/heads/main"]

  validation {
    condition     = length(var.allowed_workflow_refs) > 0
    error_message = "allowed_workflow_refs must contain at least one ref."
  }
}

variable "build_roles" {
  description = <<-EOT
    Project roles granted to the packer build service account. The GCE image
    build needs to create/manage builder VMs, run them as a service account,
    write GCE images, reach the builder over IAP (internal-IP builds, no
    external IP per the org policy), and export images to GCS via Cloud Build.
  EOT
  type        = list(string)
  default = [
    # compute.admin (superset of instanceAdmin.v1 + storageAdmin) is what the
    # `gcloud compute images export` Cloud Build identity needs: daisy creates
    # and tears down the export worker VM, its disks and snapshots, then writes
    # the GCE image - no narrower predefined role covers that whole lifecycle.
    "roles/compute.admin",
    "roles/iap.tunnelResourceAccessor",
    "roles/storage.admin",
    "roles/cloudbuild.builds.editor",
    "roles/serviceusage.serviceUsageConsumer",
    # Reach the PRIVATE GKE control plane over Connect Gateway (#1723): the
    # gateway roles authorize the fleet-membership impersonation, and
    # container.admin authorizes the actual kubectl apply via GKE's IAM->RBAC
    # mapping (the deploy applies cluster-scoped objects: namespaces, CRDs,
    # cluster services). Together these replace the old public-endpoint +
    # runner-IP-allowlist access path removed from _gcp-dev.yml.
    "roles/gkehub.gatewayEditor",
    "roles/gkehub.viewer",
    "roles/container.admin",
  ]
}
