output "assets_bucket_name" {
  description = "GCS bucket for shared platform assets."
  value       = google_storage_bucket.assets.name
}

output "audit_logs_bucket_name" {
  description = "Terminal GCS access-log sink for deployment-owned buckets."
  value       = google_storage_bucket.audit_logs.name
  depends_on  = [google_storage_bucket_iam_member.audit_log_writer]
}
