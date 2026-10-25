# Project-level Cloud Audit Logs Data Access configuration for one service (#2535).
#
# google_project_iam_audit_config is authoritative for its project/service pair:
# exactly one owner may manage each pair, and applying it replaces any audit log
# types set for that service outside Terraform. No caller is exempted, so every
# authenticated call to the service writes a Data Access record.
resource "google_project_iam_audit_config" "this" {
  count = var.enabled ? 1 : 0

  project = var.project_id
  service = var.service

  dynamic "audit_log_config" {
    for_each = toset(var.log_types)
    content {
      log_type = audit_log_config.value
    }
  }
}
