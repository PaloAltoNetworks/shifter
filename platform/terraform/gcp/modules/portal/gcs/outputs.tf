output "assets_bucket_name" {
  description = "GCS bucket for shared platform assets."
  value       = google_storage_bucket.assets.name
}
