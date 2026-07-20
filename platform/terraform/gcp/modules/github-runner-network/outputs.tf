output "network_id" {
  description = "Identifier of the dedicated runner VPC."
  value       = google_compute_network.runner.id
}

output "network_name" {
  description = "Name of the dedicated runner VPC."
  value       = google_compute_network.runner.name
}

output "subnet_id" {
  description = "Identifier of the private runner subnet."
  value       = google_compute_subnetwork.runner.id
}

output "subnet_self_link" {
  description = "Self-link of the private runner subnet (for the instance network interface)."
  value       = google_compute_subnetwork.runner.self_link
}

output "nat_ip" {
  description = "Reserved static Cloud NAT egress address for the runner subnet."
  value       = google_compute_address.runner_nat.address
}
