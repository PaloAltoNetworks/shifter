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
