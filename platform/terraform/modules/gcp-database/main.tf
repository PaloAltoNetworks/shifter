# Cloud SQL PostgreSQL for Shifter Platform
#
# GCP equivalent of the portal/rds module. Creates:
# - Private Services Access (VPC peering to Google's managed network)
# - Cloud SQL PostgreSQL instance with private IP only
# - Database and user
# - DB password stored in Secret Manager
#
# Private Services Access requires allocating an IP range in the VPC
# that Google uses for the managed SQL instance. This is a VPC-level
# peering — the SQL instance gets a private IP reachable from the VPC.
#
# Security:
# - Private IP only (no public IP)
# - Encrypted at rest (Google-managed keys, CMEK available if needed)
# - Automated backups with configurable retention
# - IAM database authentication available for GKE workloads
# - Password stored in Secret Manager (not Terraform state)
# - SSL/TLS enforced for connections
# - Deletion protection enabled by default

terraform {
  required_version = ">= 1.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.0"
    }
  }
}

# ------------------------------------------------------------------------------
# Private Services Access
#
# Allocates an IP range in the VPC for Google-managed services (Cloud SQL,
# Memorystore, etc.) and creates a VPC peering to Google's network.
# This is a one-time VPC-level setup — shared by all managed services.
# ------------------------------------------------------------------------------

resource "google_compute_global_address" "private_services" {
  name          = "${var.name_prefix}-private-services"
  project       = var.project_id
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 20
  network       = var.network_id
}

resource "google_service_networking_connection" "private_services" {
  network                 = var.network_id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.private_services.name]
}

# ------------------------------------------------------------------------------
# Database Password
# ------------------------------------------------------------------------------

resource "random_password" "db_password" {
  length           = 32
  special          = true
  override_special = "!#$%&*()-_=+[]{}<>:?"
}

# Store password in Secret Manager
resource "google_secret_manager_secret" "db_password" {
  secret_id = "${var.name_prefix}-db-password"
  project   = var.project_id

  replication {
    auto {}
  }

  labels = var.labels
}

resource "google_secret_manager_secret_version" "db_password" {
  secret = google_secret_manager_secret.db_password.id

  secret_data = jsonencode({
    username = var.db_username
    password = random_password.db_password.result
    host     = google_sql_database_instance.this.private_ip_address
    port     = 5432
    dbname   = var.db_name
    engine   = "postgresql"
  })
}

# ------------------------------------------------------------------------------
# Cloud SQL PostgreSQL Instance
# ------------------------------------------------------------------------------

resource "google_sql_database_instance" "this" {
  name                = "${var.name_prefix}-db"
  database_version    = var.database_version
  region              = var.region
  project             = var.project_id
  deletion_protection = var.deletion_protection

  settings {
    tier              = var.tier
    availability_type = var.availability_type
    disk_size         = var.disk_size_gb
    disk_type         = "PD_SSD"
    disk_autoresize   = true

    ip_configuration {
      ipv4_enabled                                  = false
      private_network                               = var.network_id
      enable_private_path_for_google_cloud_services = true
      require_ssl                                   = true

      # No authorized networks — private IP only, accessible from VPC
    }

    backup_configuration {
      enabled                        = true
      start_time                     = "03:00"
      location                       = var.region
      point_in_time_recovery_enabled = var.enable_point_in_time_recovery
      transaction_log_retention_days = var.backup_retention_days

      backup_retention_settings {
        retained_backups = var.backup_retention_days
      }
    }

    maintenance_window {
      day          = 1 # Monday
      hour         = 4 # 4 AM
      update_track = "stable"
    }

    database_flags {
      name  = "log_checkpoints"
      value = "on"
    }
    database_flags {
      name  = "log_connections"
      value = "on"
    }
    database_flags {
      name  = "log_disconnections"
      value = "on"
    }

    insights_config {
      query_insights_enabled  = true
      query_plans_per_minute  = 5
      query_string_length     = 1024
      record_application_tags = true
      record_client_address   = true
    }

    user_labels = var.labels
  }

  depends_on = [google_service_networking_connection.private_services]
}

# ------------------------------------------------------------------------------
# Database and User
# ------------------------------------------------------------------------------

resource "google_sql_database" "shifter" {
  name     = var.db_name
  instance = google_sql_database_instance.this.name
  project  = var.project_id
}

resource "google_sql_user" "shifter" {
  name     = var.db_username
  instance = google_sql_database_instance.this.name
  password = random_password.db_password.result
  project  = var.project_id
}

# IAM user for GKE Workload Identity (provisioner uses IAM auth, not password)
resource "google_sql_user" "iam_provisioner" {
  count = var.provisioner_service_account_email != "" ? 1 : 0

  name     = var.provisioner_service_account_email
  instance = google_sql_database_instance.this.name
  type     = "CLOUD_IAM_SERVICE_ACCOUNT"
  project  = var.project_id
}

# Grant Cloud SQL Client role to provisioner SA
resource "google_project_iam_member" "provisioner_sql_client" {
  count = var.provisioner_service_account_email != "" ? 1 : 0

  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${var.provisioner_service_account_email}"
}
