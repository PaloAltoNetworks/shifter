# Project Data Access audit config contract test (#2535).
#
# Credential-free: mock_provider synthesizes the google provider. Run with:
#   terraform -chdir=platform/terraform/gcp/modules/project-audit-config test

mock_provider "google" {}

variables {
  project_id = "shifter-test"
  service    = "aiplatform.googleapis.com"
  log_types  = ["DATA_READ", "DATA_WRITE"]
}

run "enabled_config_logs_every_requested_type_without_exemptions" {
  command = plan

  assert {
    condition     = length(google_project_iam_audit_config.this) == 1
    error_message = "An enabled audit config must exist (#2535)."
  }

  assert {
    condition     = google_project_iam_audit_config.this[0].service == "aiplatform.googleapis.com"
    error_message = "The audit config must target the requested service."
  }

  assert {
    condition     = toset([for entry in google_project_iam_audit_config.this[0].audit_log_config : entry.log_type]) == toset(["DATA_READ", "DATA_WRITE"])
    error_message = "The audit config must log DATA_READ and DATA_WRITE (#2535)."
  }

  assert {
    condition     = alltrue([for entry in google_project_iam_audit_config.this[0].audit_log_config : length(coalesce(entry.exempted_members, [])) == 0])
    error_message = "The audit config must not exempt any caller (#2535)."
  }
}

run "disabled_config_creates_nothing" {
  command = plan

  variables {
    enabled = false
  }

  assert {
    condition     = length(google_project_iam_audit_config.this) == 0
    error_message = "An operator-disabled audit config must not be created (#2535)."
  }
}

run "unknown_log_type_is_rejected" {
  command = plan

  variables {
    log_types = ["DATA_READ", "EVERYTHING"]
  }

  expect_failures = [var.log_types]
}
