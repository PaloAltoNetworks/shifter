# ADR-059 / M06: no keys and no model authority on application or participant SAs.
locals {
  model_projects = var.model_broker.enabled ? var.model_broker.model_projects : {}
}

resource "terraform_data" "model_project_boundary" {
  count = var.model_broker.enabled ? 1 : 0
  lifecycle {
    precondition {
      condition     = !contains(keys(local.model_projects), var.project_id) && !contains(keys(local.model_projects), var.dynamic_secret_project_id)
      error_message = "Model projects must be dedicated outside platform and dynamic-secret projects."
    }
  }
}

# Existing projects only. API activation and billing/model/effective-IAM readback
# are deployment onboarding obligations, not participant or broker permissions.
module "model_project_services" {
  for_each          = local.model_projects
  source            = "../../project-services"
  project_id        = each.key
  required_services = toset(["aiplatform.googleapis.com", "iamcredentials.googleapis.com"])
  depends_on        = [terraform_data.model_project_boundary]
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
  member             = "serviceAccount:${var.project_id}.svc.id.goog[shifter-platform/model-broker]"
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
    gsa              = try(google_service_account.model_broker[0].email, "")
    model_identities = { for project, account in google_service_account.model_invocation : project => account.email }
  }
}
