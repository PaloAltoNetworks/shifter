output "package_bucket" {
  value       = google_storage_bucket.packages.name
  description = "Set SHIFTER_RAES_PACKAGE_BUCKET in the existing tenant runtime configuration."
}
