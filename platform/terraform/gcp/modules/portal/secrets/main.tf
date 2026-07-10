resource "random_password" "django_secret_key" {
  length  = 64
  special = true
}

resource "random_id" "field_encryption_key" {
  byte_length = 32
}

resource "random_id" "guacamole_json_auth_secret" {
  byte_length = 32
}

resource "google_secret_manager_secret" "runtime" {
  for_each = var.runtime_secrets

  project   = var.project_id
  secret_id = "${var.name_prefix}-${each.key}"
  labels    = var.common_labels

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "runtime_seeded" {
  for_each = {
    app = jsonencode({
      django_secret_key    = random_password.django_secret_key.result
      field_encryption_key = random_id.field_encryption_key.b64_url
    })
    db = jsonencode({
      host     = var.cloud_sql_private_ip
      port     = 5432
      dbname   = var.cloud_sql_platform_database_name
      username = var.cloud_sql_platform_user_name
      password = var.cloud_sql_db_password
    })
    "guacamole-db" = jsonencode({
      host     = var.cloud_sql_private_ip
      port     = 5432
      dbname   = var.cloud_sql_guacamole_database_name
      username = var.cloud_sql_guacamole_user_name
      password = var.cloud_sql_guacamole_db_password
    })
    "guacamole-json-auth" = random_id.guacamole_json_auth_secret.hex
    redis = jsonencode({
      password       = var.redis_auth_string
      server_ca_cert = var.redis_server_ca_cert
    })
  }

  secret      = google_secret_manager_secret.runtime[each.key].id
  secret_data = each.value
}
