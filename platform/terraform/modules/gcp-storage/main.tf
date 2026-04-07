# GCS Bucket for Shifter Object Storage
#
# Stores agent installer files, range artifacts, etc.
# GCP equivalent of the S3 agent bucket.

terraform {
  required_version = ">= 1.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }
}

resource "google_storage_bucket" "this" {
  name     = "${var.name_prefix}-storage"
  location = var.region
  project  = var.project_id

  uniform_bucket_level_access = true

  versioning {
    enabled = false
  }

  labels = var.labels
}

# GKE node SA can read (download agents to range VMs)
resource "google_storage_bucket_iam_member" "gke_reader" {
  bucket = google_storage_bucket.this.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${var.gke_node_service_account_email}"
}

# CI/CD SA can write (upload new agent builds)
resource "google_storage_bucket_iam_member" "cicd_writer" {
  count = var.cicd_service_account_email != "" ? 1 : 0

  bucket = google_storage_bucket.this.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${var.cicd_service_account_email}"
}
