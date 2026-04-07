# GCP dev environment outputs

# Network
output "network_name" {
  description = "VPC network name"
  value       = module.network.network_name
}

output "gke_subnet_name" {
  description = "GKE subnet name"
  value       = module.network.gke_subnet_name
}

# GKE Cluster
output "cluster_name" {
  description = "GKE cluster name"
  value       = module.gke.cluster_name
}

output "cluster_endpoint" {
  description = "GKE cluster API endpoint"
  value       = module.gke.cluster_endpoint
}

output "kubevirt_node_pool_name" {
  description = "KubeVirt node pool name"
  value       = module.gke.kubevirt_node_pool_name
}

# KubeVirt + Artifact Registry
output "artifact_registry_repository" {
  description = "Artifact Registry path for VM disk images (use in containerDisk image refs)"
  value       = module.kubevirt.artifact_registry_repository
}

# Storage
output "storage_bucket_name" {
  description = "GCS bucket for agent files and artifacts"
  value       = module.storage.bucket_name
}

# Pub/Sub
output "range_events_topic" {
  description = "Pub/Sub topic for range status events"
  value       = module.pubsub.range_events_topic_id
}

# Database
output "db_private_ip" {
  description = "Cloud SQL private IP"
  value       = module.database.private_ip
}

output "db_connection_name" {
  description = "Cloud SQL connection name (for Cloud SQL Proxy)"
  value       = module.database.connection_name
}
