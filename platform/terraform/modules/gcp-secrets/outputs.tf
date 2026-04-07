output "django_secret_key_id" {
  description = "Secret Manager secret ID for Django secret key"
  value       = google_secret_manager_secret.django_secret_key.secret_id
}

output "db_password_id" {
  description = "Secret Manager secret ID for database password"
  value       = google_secret_manager_secret.db_password.secret_id
}

output "field_encryption_key_id" {
  description = "Secret Manager secret ID for field encryption key"
  value       = google_secret_manager_secret.field_encryption_key.secret_id
}
