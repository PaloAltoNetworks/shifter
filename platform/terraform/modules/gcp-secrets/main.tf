# Secret Manager for Shifter Platform Secrets
#
# GCP equivalent of AWS Secrets Manager + SSM Parameter Store.
# Creates secret containers (not values — those are set manually or by CI/CD).

terraform {
  required_version = ">= 1.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }
}

# Django secret key
resource "google_secret_manager_secret" "django_secret_key" {
  secret_id = "${var.name_prefix}-django-secret-key"
  project   = var.project_id

  replication {
    auto {}
  }

  labels = var.labels
}

# Database password
resource "google_secret_manager_secret" "db_password" {
  secret_id = "${var.name_prefix}-db-password"
  project   = var.project_id

  replication {
    auto {}
  }

  labels = var.labels
}

# Field encryption key (for encrypted model fields)
resource "google_secret_manager_secret" "field_encryption_key" {
  secret_id = "${var.name_prefix}-field-encryption-key"
  project   = var.project_id

  replication {
    auto {}
  }

  labels = var.labels
}

# Grant GKE workload identity access to secrets
# Portal and provisioner pods use Workload Identity to read secrets
resource "google_secret_manager_secret_iam_member" "django_key_accessor" {
  count = var.portal_service_account_email != "" ? 1 : 0

  secret_id = google_secret_manager_secret.django_secret_key.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${var.portal_service_account_email}"
}

resource "google_secret_manager_secret_iam_member" "db_password_accessor" {
  count = var.portal_service_account_email != "" ? 1 : 0

  secret_id = google_secret_manager_secret.db_password.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${var.portal_service_account_email}"
}

resource "google_secret_manager_secret_iam_member" "encryption_key_accessor" {
  count = var.portal_service_account_email != "" ? 1 : 0

  secret_id = google_secret_manager_secret.field_encryption_key.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${var.portal_service_account_email}"
}
