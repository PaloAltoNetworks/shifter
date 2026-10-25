output "enabled_log_types" {
  description = "Data Access log types this module enabled; empty when disabled."
  value       = var.enabled ? sort(var.log_types) : []
}
