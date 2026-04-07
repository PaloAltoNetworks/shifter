# GCP dev environment outputs

output "network_name" {
  description = "VPC network name"
  value       = module.network.network_name
}

output "gke_subnet_name" {
  description = "GKE subnet name (for GKE cluster config)"
  value       = module.network.gke_subnet_name
}

output "gke_pods_range_name" {
  description = "Secondary range name for pods (for GKE cluster config)"
  value       = module.network.gke_pods_range_name
}

output "gke_services_range_name" {
  description = "Secondary range name for services (for GKE cluster config)"
  value       = module.network.gke_services_range_name
}
