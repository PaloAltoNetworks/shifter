output "instance_name" {
  description = "Cloud SQL instance name"
  value       = google_sql_database_instance.this.name
}

output "private_ip" {
  description = "Private IP address of the Cloud SQL instance"
  value       = google_sql_database_instance.this.private_ip_address
}

output "connection_name" {
  description = "Cloud SQL connection name (project:region:instance — used by Cloud SQL Proxy)"
  value       = google_sql_database_instance.this.connection_name
}

output "db_name" {
  description = "Database name"
  value       = google_sql_database.shifter.name
}

output "db_username" {
  description = "Database admin username"
  value       = google_sql_user.shifter.name
}

output "db_password_secret_id" {
  description = "Secret Manager secret ID containing DB credentials"
  value       = google_secret_manager_secret.db_password.secret_id
}

output "private_services_peering_range" {
  description = "IP range allocated for Private Services Access (shared by Cloud SQL, Memorystore, etc.)"
  value       = google_compute_global_address.private_services.name
}
