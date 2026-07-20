resource "random_password" "db_password" {
  length  = 32
  special = true
}

resource "random_password" "guacamole_db_password" {
  length  = 32
  special = true
}

resource "google_sql_database_instance" "platform" {
  name                = "${var.name_prefix}-pg"
  project             = var.project_id
  region              = var.region
  database_version    = var.cloud_sql_database_version
  deletion_protection = var.cloud_sql_deletion_protection

  settings {
    tier                        = var.cloud_sql_tier
    availability_type           = var.cloud_sql_availability_type
    disk_size                   = var.cloud_sql_disk_size_gb
    disk_type                   = "PD_SSD"
    deletion_protection_enabled = var.cloud_sql_deletion_protection

    backup_configuration {
      enabled = true
    }

    ip_configuration {
      ipv4_enabled                                  = false
      private_network                               = var.platform_network_id
      enable_private_path_for_google_cloud_services = true
      ssl_mode                                      = "ENCRYPTED_ONLY"
    }

    database_flags {
      name  = "log_connections"
      value = "on"
    }

    user_labels = var.common_labels
  }
}

resource "google_sql_database" "platform" {
  name     = var.cloud_sql_database_name
  project  = var.project_id
  instance = google_sql_database_instance.platform.name
}

resource "google_sql_database" "guacamole" {
  name     = "guacamole"
  project  = var.project_id
  instance = google_sql_database_instance.platform.name
}

resource "google_sql_user" "platform" {
  name     = var.cloud_sql_user_name
  project  = var.project_id
  instance = google_sql_database_instance.platform.name
  password = random_password.db_password.result
}

resource "google_sql_user" "guacamole" {
  name     = "guacamole_admin"
  project  = var.project_id
  instance = google_sql_database_instance.platform.name
  password = random_password.guacamole_db_password.result
}
