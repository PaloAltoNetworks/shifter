# Native API roles follow Google's documented IAM conditions and directory API
# permission map. Keep these additive; deliberate operator bindings remain
# separately assigned and are never reconciled away by workload configuration.
locals {
  native_sql_workloads = var.cloud_sql_iam_auth ? setunion(
    toset(["portal", "workers", "ctf-scheduler", "provisioner-launcher", "provisioner"]),
    var.openfga_enabled ? toset(["openfga-runtime", "openfga-admin", "openfga-migrator"]) : toset([])
  ) : toset([])
  native_sql_roles = merge(
    merge([for workload in local.native_sql_workloads : {
      for role in ["roles/cloudsql.client", "roles/cloudsql.instanceUser"] : "${workload}:${role}" => {
        workload = workload
        role     = role
      }
    }]...),
    var.cloud_sql_iam_auth ? {
      "guacamole-client:roles/cloudsql.client" = { workload = "guacamole-client", role = "roles/cloudsql.client" }
      "migrator:roles/cloudsql.client"         = { workload = "migrator", role = "roles/cloudsql.client" }
    } : {}
  )
}

resource "google_sql_user" "native" {
  for_each = local.native_sql_workloads

  project         = var.project_id
  instance        = var.cloud_sql_instance_name
  name            = trimsuffix(google_service_account.workload[each.key].email, ".gserviceaccount.com")
  type            = "CLOUD_IAM_SERVICE_ACCOUNT"
  deletion_policy = "ABANDON"
}

resource "google_project_iam_member" "native_sql" {
  for_each = local.native_sql_roles

  project = var.project_id
  role    = each.value.role
  member  = "serviceAccount:${google_service_account.workload[each.value.workload].email}"
  condition {
    title       = "platform_sql_instance"
    description = "Connector and login authority apply only to this installation's Cloud SQL instance."
    expression  = "resource.name == 'projects/${var.project_id}/instances/${var.cloud_sql_instance_name}'"
  }
}

resource "google_project_iam_custom_role" "directory_reader" {
  project     = var.project_id
  role_id     = "shifterDirectoryReader"
  title       = "Shifter directory lifecycle reader"
  description = "Native user-state and revocation rechecks; no configuration, hash export, or user mutation."
  permissions = ["firebaseauth.users.get"]
}

resource "google_project_iam_member" "directory_reader" {
  project = var.project_id
  role    = google_project_iam_custom_role.directory_reader.id
  member  = "serviceAccount:${google_service_account.workload["portal"].email}"
}
