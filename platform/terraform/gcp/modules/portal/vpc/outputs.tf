output "platform_network_id" {
  description = "Identifier of the platform VPC."
  value       = google_compute_network.platform.id
}

output "network_name" {
  description = "Name of the platform VPC."
  value       = google_compute_network.platform.name
}

output "gke_subnetwork_name" {
  description = "Name of the GKE subnetwork."
  value       = google_compute_subnetwork.gke.name
}

output "gke_subnetwork_id" {
  description = "Identifier of the GKE subnetwork."
  value       = google_compute_subnetwork.gke.id
}
