# ADR-059 / M06: no keys and no model authority on application or participant SAs.
locals {
  model_projects = var.model_broker.enabled ? var.model_broker.model_projects : {}
}

# Existing projects only. API activation and billing/model/effective-IAM readback
# are deployment onboarding obligations, not participant or broker permissions.
# A deployment may select its platform/dynamic-secret project as a model source;
# the broker and invocation service accounts remain distinct and least-privilege.
module "model_project_services" {
  for_each          = local.model_projects
  source            = "../../project-services"
  project_id        = each.key
  required_services = toset(["aiplatform.googleapis.com", "iamcredentials.googleapis.com"])
}

resource "google_service_account" "model_broker" {
  count        = var.model_broker.enabled ? 1 : 0
  project      = var.project_id
  account_id   = "${substr(replace(var.name_prefix, "-", ""), 0, 17)}-model-broker"
  display_name = "Shifter deployment model broker"
}

resource "google_service_account_iam_member" "model_broker_workload_identity" {
  count              = var.model_broker.enabled ? 1 : 0
  service_account_id = google_service_account.model_broker[0].name
  role               = "roles/iam.workloadIdentityUser"
  member             = "serviceAccount:${var.workload_identity_pool}[shifter-platform/model-broker]"
}

resource "google_service_account" "model_invocation" {
  for_each     = local.model_projects
  project      = each.key
  account_id   = each.value
  display_name = "Shifter ${var.environment} invocation only"
  depends_on   = [module.model_project_services]
}

resource "google_project_iam_custom_role" "model_invoke" {
  for_each    = local.model_projects
  project     = each.key
  role_id     = "shifterModelInvoke"
  title       = "Shifter model invocation"
  permissions = ["aiplatform.endpoints.predict"]
}

resource "google_project_iam_custom_role" "model_token" {
  for_each    = local.model_projects
  project     = each.key
  role_id     = "shifterModelAccessToken"
  title       = "Shifter exact model token issuance"
  permissions = ["iam.serviceAccounts.getAccessToken"]
}

resource "google_project_iam_member" "model_invocation" {
  for_each = local.model_projects
  project  = each.key
  role     = google_project_iam_custom_role.model_invoke[each.key].name
  member   = "serviceAccount:${google_service_account.model_invocation[each.key].email}"
}

resource "google_service_account_iam_member" "model_target_token" {
  for_each           = local.model_projects
  service_account_id = google_service_account.model_invocation[each.key].name
  role               = google_project_iam_custom_role.model_token[each.key].name
  member             = "serviceAccount:${google_service_account.model_broker[0].email}"
}

output "model_broker_identity" {
  description = "Broker-only GSA and exact invocation targets, never credentials."
  value = {
    gsa                    = try(google_service_account.model_broker[0].email, "")
    provisioner_subject    = var.model_broker.enabled ? google_service_account.workload["provisioner"].email : ""
    broker_subject_id      = try(google_service_account.model_broker[0].unique_id, "")
    provisioner_subject_id = var.model_broker.enabled ? google_service_account.workload["provisioner"].unique_id : ""
    model_identities       = { for project, account in google_service_account.model_invocation : project => account.email }
  }
}

# Tenant source credentials are platform-owned, separate from participant secret
# delivery. Creation authorizes on the project parent; all payload/lifecycle
# permissions are constrained to the server-generated source namespace.
resource "google_project_iam_custom_role" "model_source_create" {
  count       = var.model_broker.enabled ? 1 : 0
  project     = var.project_id
  role_id     = "shifterModelSourceCreate"
  title       = "Shifter model source credential creation"
  permissions = ["secretmanager.secrets.create"]
}

resource "google_project_iam_member" "model_source_create" {
  count   = var.model_broker.enabled ? 1 : 0
  project = var.project_id
  role    = google_project_iam_custom_role.model_source_create[0].name
  member  = "serviceAccount:${google_service_account.workload["portal"].email}"
}

resource "google_project_iam_custom_role" "model_source_write" {
  count       = var.model_broker.enabled ? 1 : 0
  project     = var.project_id
  role_id     = "shifterModelSourceWrite"
  title       = "Shifter owned model source credential lifecycle"
  permissions = ["secretmanager.versions.add", "secretmanager.versions.access", "secretmanager.secrets.delete"]
}

resource "google_project_iam_member" "model_source_write" {
  count   = var.model_broker.enabled ? 1 : 0
  project = var.project_id
  role    = google_project_iam_custom_role.model_source_write[0].name
  member  = "serviceAccount:${google_service_account.workload["portal"].email}"
  condition {
    title      = "owned_model_source_credentials"
    expression = "resource.name.startsWith('projects/${data.google_project.platform.number}/secrets/shifter-model-source-')"
  }
}

resource "google_project_iam_member" "model_source_control_read" {
  count   = var.model_broker.enabled ? 1 : 0
  project = var.project_id
  role    = "roles/secretmanager.secretAccessor"
  member  = "serviceAccount:${google_service_account.workload["workers"].email}"
  condition {
    title      = "owned_model_source_credentials"
    expression = "resource.name.startsWith('projects/${data.google_project.platform.number}/secrets/shifter-model-source-')"
  }
}
