output "gke_cluster_name" {
  description = "Name of the GKE cluster."
  value       = google_container_cluster.platform.name
}

output "gke_cluster_location" {
  description = "Location of the GKE cluster."
  value       = google_container_cluster.platform.location
}

output "workload_identity_pool" {
  description = "GKE Workload Identity pool."
  value       = "${var.project_id}.svc.id.goog"
}
