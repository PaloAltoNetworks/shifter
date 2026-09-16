resource "google_storage_bucket" "audit_logs" {
  # checkov:skip=CKV_GCP_62:This is the access-log sink for the assets bucket; making it log to itself creates recursive log objects, while a second sink would only move the same terminal-sink exception. See ADR-004-R11 exception (#2084).
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

# Cloud Storage usage-log delivery runs as this Google-managed group. The sink
# uses uniform bucket-level access, so the required WRITE permission is granted
# with the narrow objectCreator IAM role rather than a bucket ACL.
resource "google_storage_bucket_iam_member" "audit_log_writer" {
  # Gated for Domain Restricted Sharing orgs: the google.com group is rejected by
  # iam.allowedPolicyMemberDomains (Error 412) where the policy does not permit the
  # Google customer. Cloud Audit Logs are unaffected (google_project_iam_audit_config).
  count  = var.enable_gcs_usage_log_delivery ? 1 : 0
  bucket = google_storage_bucket.audit_logs.name
  role   = "roles/storage.objectCreator"
  member = "group:cloud-storage-analytics@google.com"
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

  depends_on = [google_storage_bucket_iam_member.audit_log_writer]

  # Browser signed-URL uploads/downloads (XDR agent MSIs, experiment artifacts)
  # are issued to the portal origin, so the bucket must answer CORS preflights or
  # the PUT/GET is blocked. Scoped to the deployment's public hostname.
  dynamic "cors" {
    for_each = var.public_hostname == "" ? [] : [1]
    content {
      origin          = ["https://${var.public_hostname}"]
      method          = ["GET", "HEAD", "PUT", "POST"]
      response_header = ["Content-Type", "Content-MD5", "ETag", "x-goog-resumable"]
      max_age_seconds = 3600
    }
  }
}
