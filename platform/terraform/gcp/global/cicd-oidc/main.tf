# Foundational GitHub Actions -> GCP OIDC/WIF identity root (issue #615 follow-up).
#
# The WIF pool/provider and purpose-scoped service accounts are the identities
# CI authenticates as. They must OUTLIVE the platform: a
# `gcp-dev-destroy` tears down the platform-core root, and the subsequent CI
# rebuild has to authenticate (via this WIF) to run at all. So this identity
# lives in its own Terraform root with a state prefix separate from the platform
# root -- exactly like platform/terraform/gcp/global/github-runner -- and the
# platform destroy never touches it. This matches the README "Fresh GCP Account
# Order" step 2, where WIF is configured before (and independently of) the
# platform deploy.
#
# The network-coupled packer build-infra (builder subnet, IAP firewall, image
# bucket) stays in the platform-core root because it depends on the platform VPC
# and Cloud NAT; it references this SA by its deterministic email. The separate
# first-bake image network has no platform dependency and is instantiated here
# through the image-build-network module so it exists before platform bootstrap.

terraform {
  required_version = ">= 1.9.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 8.1"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

module "cicd_oidc_identity" {
  source = "../../modules/cicd-oidc-identity"

  project_id                             = var.project_id
  project_number                         = var.project_number
  github_repository_id                   = var.github_repository_id
  github_owner_id                        = var.github_owner_id
  github_subject_format                  = var.github_subject_format
  purpose_contexts                       = var.purpose_contexts
  release_evidence_bucket_name           = var.release_evidence_bucket_name
  region                                 = var.region
  environment                            = var.environment
  name_prefix                            = var.name_prefix
  github_org                             = var.github_org
  github_repo                            = var.github_repo
  build_read_bucket_names                = var.build_read_bucket_names
  promotion_reader_service_account_email = var.promotion_reader_service_account_email
  terraform_state_bucket_name            = var.terraform_state_bucket_name
  platform_external_bucket_names         = var.platform_external_bucket_names
}
