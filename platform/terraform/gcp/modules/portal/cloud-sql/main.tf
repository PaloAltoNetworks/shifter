resource "random_password" "db_password" {
  length  = 32
  special = true

  # Rotation 1 repairs tenants whose write-only Cloud SQL user password
  # drifted from the Terraform-managed Secret Manager payload. Increment this
  # value for an intentional future rotation so the SQL user and secret
  # version are updated together.
  keepers = {
    rotation = 1
  }
}

resource "random_password" "runtime_db_password" {
  length  = 32
  special = true

  keepers = {
    rotation = 1
  }
}

resource "random_password" "provisioner_db_password" {
  length  = 32
  special = true

  keepers = {
    rotation = 1
  }
}

resource "random_password" "guacamole_db_password" {
  length  = 32
  special = true
}

resource "google_sql_database_instance" "platform" {
  # checkov:skip=CKV_GCP_6:Reviewed false positive: ssl_mode=ENCRYPTED_ONLY rejects plaintext connections; Checkov 3.2 does not recognize the provider's replacement for require_ssl. See ADR-004-R11 exception (#2084).
  # checkov:skip=CKV_GCP_79:The supported PostgreSQL major is a release/migration decision; silently changing the module default to Checkov's moving "latest" target can trigger a destructive major upgrade. See ADR-004-R11 exception (#2084).
  # checkov:skip=CKV_GCP_109:Error-statement logging can capture participant data and credentials embedded in failed queries. Error severity and pgaudit logging remain enabled. See ADR-004-R11 exception (#2084).
  # checkov:skip=CKV_GCP_111:Statement-level logging can capture participant data and credentials embedded in queries. Connection, error, duration, lock-wait, and pgaudit logging remain enabled. See ADR-004-R11 exception (#2084).
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

    database_flags {
      name  = "log_checkpoints"
      value = "on"
    }

    database_flags {
      name  = "log_disconnections"
      value = "on"
    }

    database_flags {
      name  = "log_duration"
      value = "on"
    }

    database_flags {
      name  = "log_hostname"
      value = "on"
    }

    database_flags {
      name  = "log_lock_waits"
      value = "on"
    }

    database_flags {
      name  = "log_min_messages"
      value = "error"
    }

    database_flags {
      name  = "cloudsql.enable_pgaudit"
      value = "on"
    }

    dynamic "database_flags" {
      for_each = var.cloud_sql_iam_auth ? [1] : []
      content {
        name  = "cloudsql.iam_authentication"
        value = "on"
      }
    }

    user_labels = var.common_labels
  }

  # Cloud SQL may grow an auto-resized disk but cannot shrink it. Reconciling
  # the configured floor after growth would otherwise plan a destructive
  # replacement of the deletion-protected production database.
  lifecycle {
    ignore_changes = [settings[0].disk_size]
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

resource "google_sql_database" "openfga" {
  count    = var.openfga_enabled ? 1 : 0
  name     = "openfga"
  project  = var.project_id
  instance = google_sql_database_instance.platform.name
}

# deletion_policy = "ABANDON": on PostgreSQL a role that owns objects cannot be
# dropped via the Cloud SQL API ("role X cannot be dropped because some objects
# depend on it"), which stalls `terraform destroy` before the instance is removed
# (#2258). ABANDON drops the resource from state instead of issuing DROP ROLE; the
# instance deletion that follows removes the role and its objects with it.
resource "google_sql_user" "platform" {
  name            = var.cloud_sql_user_name
  project         = var.project_id
  instance        = google_sql_database_instance.platform.name
  password        = random_password.db_password.result
  deletion_policy = "ABANDON"
}

resource "google_sql_user" "runtime" {
  name            = "portal_runtime"
  project         = var.project_id
  instance        = google_sql_database_instance.platform.name
  password        = random_password.runtime_db_password.result
  deletion_policy = "ABANDON"
}

resource "google_sql_user" "provisioner" {
  name     = "provisioner_runtime"
  project  = var.project_id
  instance = google_sql_database_instance.platform.name
  password = random_password.provisioner_db_password.result
}

resource "google_sql_user" "guacamole" {
  name            = "guacamole_admin"
  project         = var.project_id
  instance        = google_sql_database_instance.platform.name
  password        = random_password.guacamole_db_password.result
  deletion_policy = "ABANDON"
}
