mock_provider "google" {
  mock_data "google_project" {
    defaults = { number = "123456789012" }
  }
  mock_resource "google_service_account" {
    defaults = {
      email = "synthetic-runtime@synthetic-project.iam.gserviceaccount.com"
      name  = "projects/synthetic-project/serviceAccounts/synthetic-runtime@synthetic-project.iam.gserviceaccount.com"
    }
  }
}

variables {
  project_id                  = "synthetic-project"
  dynamic_secret_project_id   = "synthetic-project"
  environment                 = "test"
  name_prefix                 = "shifter-test"
  workload_identity_pool      = "synthetic-project.svc.id.goog"
  assets_bucket_name          = "synthetic-assets"
  terraform_state_bucket_name = "synthetic-state"
  cloud_sql_iam_auth          = true
  cloud_sql_instance_name     = "platform-pg"
  openfga_enabled             = true
  runtime_secret_ids = {
    app            = "projects/synthetic-project/secrets/app"
    db             = "projects/synthetic-project/secrets/db"
    db-migration   = "projects/synthetic-project/secrets/migrate"
    db-provisioner = "projects/synthetic-project/secrets/provisioner"
    guacamole-db   = "projects/synthetic-project/secrets/guacamole"
  }
}

run "native_workloads_keep_exact_login_and_resource_duties" {
  command = apply
  assert {
    condition     = google_sql_user.native["portal"].type == "CLOUD_IAM_SERVICE_ACCOUNT"
    error_message = "Runtime SQL users must be native attached service accounts."
  }
  assert {
    condition     = google_sql_user.native["portal"].name == "synthetic-runtime@synthetic-project.iam"
    error_message = "PostgreSQL service-account names must remove only the documented suffix."
  }
  assert {
    condition     = !contains(local.runtime_secret_reader_keys, "db") && length(local.provisioner_database_secret_binding) == 0
    error_message = "Native clients must not inherit database password secret reads."
  }
  assert {
    condition     = google_project_iam_member.native_sql["portal:roles/cloudsql.instanceUser"].condition[0].expression == "resource.name == 'projects/synthetic-project/instances/platform-pg'"
    error_message = "SQL login must be bound to the configured instance."
  }
  assert {
    condition     = contains(keys(local.native_sql_roles), "migrator:roles/cloudsql.client") && !contains(keys(local.native_sql_roles), "migrator:roles/cloudsql.instanceUser")
    error_message = "The application schema owner gets native transport only, never an incidental IAM runtime login."
  }
  assert {
    condition     = strcontains(local.dynamic_lifecycle_condition, "shifter-test-dynamic-") && strcontains(local.portal_dynamic_read_condition, "shifter-test-dynamic-participant-")
    error_message = "Canonical lifecycle and participant prefixes must also work in one project."
  }
  assert {
    condition     = google_project_iam_custom_role.directory_reader.permissions == toset(["firebaseauth.users.get"])
    error_message = "Native directory rechecks must not include configuration or hash-export authority."
  }
  assert {
    condition     = !contains(keys(local.workload_identity_members), "operator") && !contains(keys(local.workload_project_roles), "openfga-runtime")
    error_message = "Policy clients must not acquire broad operator or unrelated application roles."
  }
}
