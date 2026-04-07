# GCP Workload Identity Federation & CI/CD Service Account
#
# GCP equivalent of global/iam/ (AWS). Sets up:
# 1. Workload Identity Pool + Provider for GitHub Actions OIDC
# 2. CI/CD service account with project-level roles
# 3. GCS bucket for Terraform state
#
# After applying, add these GitHub secrets:
#   GCP_WORKLOAD_IDENTITY_PROVIDER = output.workload_identity_provider
#   GCP_SERVICE_ACCOUNT            = output.service_account_email
#   GCP_PROJECT_ID                 = output.project_id

terraform {
  required_version = ">= 1.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }
  backend "gcs" {}
}

provider "google" {
  project = var.project_id
  region  = var.region

  default_labels = {
    project     = "shifter"
    managed_by  = "terraform"
    environment = var.environment
  }
}

# ------------------------------------------------------------------------------
# Terraform State Bucket (GCS)
# ------------------------------------------------------------------------------

resource "google_storage_bucket" "terraform_state" {
  name     = "shifter-${var.environment}-terraform-state"
  location = var.region

  versioning {
    enabled = true
  }

  uniform_bucket_level_access = true

  labels = {
    purpose = "terraform-state"
  }

  lifecycle {
    prevent_destroy = true
  }
}

# ------------------------------------------------------------------------------
# Workload Identity Pool (GitHub Actions OIDC)
# GCP equivalent of AWS OIDC Provider
# ------------------------------------------------------------------------------

resource "google_iam_workload_identity_pool" "github" {
  workload_identity_pool_id = "shifter-github-${var.environment}"
  display_name              = "Shifter GitHub Actions (${var.environment})"
  description               = "Workload Identity Pool for GitHub Actions CI/CD"
}

resource "google_iam_workload_identity_pool_provider" "github" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github-oidc"
  display_name                       = "GitHub OIDC"

  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.actor"      = "assertion.actor"
    "attribute.repository" = "assertion.repository"
    "attribute.ref"        = "assertion.ref"
  }

  attribute_condition = "assertion.repository == '${var.github_org}/${var.github_repo}'"

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

# ------------------------------------------------------------------------------
# CI/CD Service Account
# GCP equivalent of AWS IAM Role for GitHub Actions
# ------------------------------------------------------------------------------

resource "google_service_account" "github_actions" {
  account_id   = "shifter-github-${var.environment}"
  display_name = "Shifter GitHub Actions CI/CD (${var.environment})"
  description  = "Service account assumed by GitHub Actions via Workload Identity Federation"
}

# Allow GitHub Actions to impersonate the service account via Workload Identity
resource "google_service_account_iam_member" "github_actions_wif" {
  service_account_id = google_service_account.github_actions.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository/${var.github_org}/${var.github_repo}"
}

# Grant project-level roles to the service account
# TODO: Scope down from Editor to least-privilege before production hardening
resource "google_project_iam_member" "github_actions_editor" {
  project = var.project_id
  role    = "roles/editor"
  member  = "serviceAccount:${google_service_account.github_actions.email}"
}

# GKE admin — needed to create and manage GKE clusters
resource "google_project_iam_member" "github_actions_gke" {
  project = var.project_id
  role    = "roles/container.admin"
  member  = "serviceAccount:${google_service_account.github_actions.email}"
}

# IAM admin — needed to manage service accounts and bindings
resource "google_project_iam_member" "github_actions_iam" {
  project = var.project_id
  role    = "roles/iam.serviceAccountAdmin"
  member  = "serviceAccount:${google_service_account.github_actions.email}"
}

# Compute admin — needed for bare metal / nested virt instances (KubeVirt)
resource "google_project_iam_member" "github_actions_compute" {
  project = var.project_id
  role    = "roles/compute.admin"
  member  = "serviceAccount:${google_service_account.github_actions.email}"
}

# Storage admin — needed for Artifact Registry, GCS buckets
resource "google_project_iam_member" "github_actions_storage" {
  project = var.project_id
  role    = "roles/storage.admin"
  member  = "serviceAccount:${google_service_account.github_actions.email}"
}

# Secret Manager admin — needed for secrets
resource "google_project_iam_member" "github_actions_secrets" {
  project = var.project_id
  role    = "roles/secretmanager.admin"
  member  = "serviceAccount:${google_service_account.github_actions.email}"
}

# Cloud SQL admin — needed for database management
resource "google_project_iam_member" "github_actions_sql" {
  project = var.project_id
  role    = "roles/cloudsql.admin"
  member  = "serviceAccount:${google_service_account.github_actions.email}"
}

# Pub/Sub admin — needed for event messaging
resource "google_project_iam_member" "github_actions_pubsub" {
  project = var.project_id
  role    = "roles/pubsub.admin"
  member  = "serviceAccount:${google_service_account.github_actions.email}"
}
