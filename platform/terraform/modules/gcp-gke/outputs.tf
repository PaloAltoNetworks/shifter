# GKE module outputs

output "cluster_name" {
  description = "Name of the GKE cluster"
  value       = google_container_cluster.this.name
}

output "cluster_endpoint" {
  description = "Endpoint for the GKE cluster API server"
  value       = google_container_cluster.this.endpoint
}

output "cluster_ca_certificate" {
  description = "Base64-encoded CA certificate for the cluster"
  value       = google_container_cluster.this.master_auth[0].cluster_ca_certificate
  sensitive   = true
}

output "cluster_location" {
  description = "Location (region) of the cluster"
  value       = google_container_cluster.this.location
}

output "node_service_account_email" {
  description = "Service account email used by GKE nodes"
  value       = google_service_account.gke_nodes.email
}

output "system_node_pool_name" {
  description = "Name of the system node pool"
  value       = google_container_node_pool.system.name
}

output "kubevirt_node_pool_name" {
  description = "Name of the KubeVirt node pool"
  value       = google_container_node_pool.kubevirt.name
}
