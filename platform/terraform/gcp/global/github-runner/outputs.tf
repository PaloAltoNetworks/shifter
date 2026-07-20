output "runner_instance_names" {
  description = "Names of the provisioned GCE runner instances (used by the IAP registration handoff)."
  value       = google_compute_instance.runner[*].name
}

output "runner_names" {
  description = "GitHub runner names to register (one per instance)."
  value       = [for i in range(var.runner_count) : "${local.name_prefix}-runner-${i + 1}"]
}

output "runner_service_account_email" {
  description = "Email of the dedicated least-privilege runner VM service account."
  value       = google_service_account.runner.email
}

output "runner_network_name" {
  description = "Name of the dedicated runner VPC."
  value       = module.runner_network.network_name
}

output "runner_nat_ip" {
  description = "Reserved static Cloud NAT egress IP for the runner subnet."
  value       = module.runner_network.nat_ip
}
