mock_provider "google" {}
mock_provider "random" {}

variables {
  project_id                    = "synthetic-project"
  region                        = "us-central1"
  name_prefix                   = "shifter-test"
  platform_network_id           = "projects/synthetic-project/global/networks/platform"
  common_labels                 = {}
  cloud_sql_iam_auth            = true
  openfga_enabled               = true
  cloud_sql_database_version    = "POSTGRES_16"
  cloud_sql_tier                = "db-custom-2-7680"
  cloud_sql_availability_type   = "REGIONAL"
  cloud_sql_disk_size_gb        = 20
  cloud_sql_database_name       = "shifter"
  cloud_sql_user_name           = "schema_owner"
  cloud_sql_deletion_protection = true
}

run "native_login_flag_and_dedicated_policy_database" {
  command = plan
  assert {
    condition = anytrue([for flag in google_sql_database_instance.platform.settings[0].database_flags :
    flag.name == "cloudsql.iam_authentication" && flag.value == "on"])
    error_message = "Native client configuration must enable Cloud SQL IAM database login."
  }
  assert {
    condition     = google_sql_database.openfga[0].name == "openfga"
    error_message = "The policy datastore must be separate from application tables on the shared instance."
  }
}
