output "control_plane_database" {
  description = "Control-plane database connection metadata."
  value = {
    instance_name = google_sql_database_instance.platform.name
    private_ip    = google_sql_database_instance.platform.private_ip_address
    port          = 5432
    database_name = google_sql_database.platform.name
    user_name     = google_sql_user.platform.name
  }
}

output "guacamole_database" {
  description = "Guacamole database connection metadata."
  value = {
    database_name = google_sql_database.guacamole.name
    user_name     = google_sql_user.guacamole.name
    host          = google_sql_database_instance.platform.private_ip_address
    port          = 5432
  }
}

output "db_password" {
  description = "Application PostgreSQL password for the control plane."
  value       = random_password.db_password.result
  sensitive   = true
}

output "guacamole_db_password" {
  description = "Guacamole PostgreSQL password."
  value       = random_password.guacamole_db_password.result
  sensitive   = true
}

output "private_ip_address" {
  description = "Cloud SQL private IP address."
  value       = google_sql_database_instance.platform.private_ip_address
}

output "platform_database_name" {
  description = "Default PostgreSQL database name for the control plane."
  value       = google_sql_database.platform.name
}

output "platform_user_name" {
  description = "Application PostgreSQL username for the control plane."
  value       = google_sql_user.platform.name
}

output "guacamole_database_name" {
  description = "Guacamole PostgreSQL database name."
  value       = google_sql_database.guacamole.name
}

output "guacamole_user_name" {
  description = "Guacamole PostgreSQL username."
  value       = google_sql_user.guacamole.name
}

output "instance_name" {
  description = "Cloud SQL instance name."
  value       = google_sql_database_instance.platform.name
}
