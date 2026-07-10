output "range_network_id" {
  description = "Identifier of the dedicated range VPC."
  value       = google_compute_network.range.id
}

output "range_network_name" {
  description = "Name of the dedicated range VPC."
  value       = google_compute_network.range.name
}
