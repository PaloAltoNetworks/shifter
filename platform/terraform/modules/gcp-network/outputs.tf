# GCP Network module outputs
#
# These are consumed by the GKE module (next slice) and later by
# portal, Cloud SQL, and Cloud NGFW modules.

output "network_id" {
  description = "Self-link of the VPC network"
  value       = google_compute_network.this.id
}

output "network_name" {
  description = "Name of the VPC network"
  value       = google_compute_network.this.name
}

output "gke_subnet_id" {
  description = "Self-link of the GKE subnet"
  value       = google_compute_subnetwork.gke.id
}

output "gke_subnet_name" {
  description = "Name of the GKE subnet"
  value       = google_compute_subnetwork.gke.name
}

output "gke_subnet_cidr" {
  description = "Primary CIDR of the GKE subnet (node IPs)"
  value       = google_compute_subnetwork.gke.ip_cidr_range
}

output "gke_pods_range_name" {
  description = "Name of the secondary range for pods (used in GKE cluster config)"
  value       = google_compute_subnetwork.gke.secondary_ip_range[0].range_name
}

output "gke_services_range_name" {
  description = "Name of the secondary range for services (used in GKE cluster config)"
  value       = google_compute_subnetwork.gke.secondary_ip_range[1].range_name
}

output "router_name" {
  description = "Name of the Cloud Router"
  value       = google_compute_router.this.name
}

output "nat_name" {
  description = "Name of the Cloud NAT"
  value       = google_compute_router_nat.this.name
}
