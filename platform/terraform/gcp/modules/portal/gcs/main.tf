resource "google_storage_bucket" "audit_logs" {
  name                        = lower("${var.project_id}-${replace(var.environment, "_", "-")}-audit-logs")
  project                     = var.project_id
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false
  labels                      = var.common_labels

  versioning {
    enabled = true
  }

  lifecycle_rule {
    action {
      type = "Delete"
    }

    condition {
      age = 30
    }
  }
}

resource "google_storage_bucket" "assets" {
  name                        = lower("${var.project_id}-${replace(var.environment, "_", "-")}-assets")
  project                     = var.project_id
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false
  labels                      = var.common_labels

  versioning {
    enabled = true
  }

  logging {
    log_bucket        = google_storage_bucket.audit_logs.name
    log_object_prefix = "assets/"
  }
}
