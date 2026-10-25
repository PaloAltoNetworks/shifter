# The image-build network is foundation-owned so it exists before the first
# platform deployment. Keep this module in the existing cicd-oidc state.
variable "enable_image_build_network" {
  description = "Create an isolated private image-build network before platform bootstrap."
  type        = bool
  default     = false
}

variable "image_build_subnet_cidr" {
  description = "Private subnet used only by disposable image builders and validators."
  type        = string
  default     = "10.201.0.0/24"
}

module "image_build_network" {
  source = "../../modules/image-build-network"

  project_id                         = var.project_id
  region                             = var.region
  name_prefix                        = var.name_prefix
  packer_build_service_account_email = module.cicd_oidc_identity.packer_build_service_account_email
  enable_image_build_network         = var.enable_image_build_network
  image_build_subnet_cidr            = var.image_build_subnet_cidr
}

# These address-only moves keep every existing foundation object in the same
# state. Retain them for tenants that have not applied the module refactor yet.
moved {
  from = google_compute_network.image_build
  to   = module.image_build_network.google_compute_network.image_build
}

moved {
  from = google_compute_subnetwork.image_build
  to   = module.image_build_network.google_compute_subnetwork.image_build
}

moved {
  from = google_compute_router.image_build
  to   = module.image_build_network.google_compute_router.image_build
}

moved {
  from = google_compute_router_nat.image_build
  to   = module.image_build_network.google_compute_router_nat.image_build
}

moved {
  from = google_compute_firewall.image_build_iap
  to   = module.image_build_network.google_compute_firewall.image_build_iap
}

moved {
  from = google_compute_firewall.image_validate_iap
  to   = module.image_build_network.google_compute_firewall.image_validate_iap
}

output "image_build_network_name" {
  description = "GCP_PACKER_NETWORK and GCP_VALIDATE_NETWORK for first-project image jobs."
  value       = module.image_build_network.image_build_network_name
}

output "image_build_subnetwork_name" {
  description = "GCP_PACKER_SUBNETWORK and GCP_VALIDATE_SUBNETWORK for first-project image jobs."
  value       = module.image_build_network.image_build_subnetwork_name
}
