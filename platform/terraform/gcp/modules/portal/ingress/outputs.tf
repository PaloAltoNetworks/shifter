output "public_ingress_ip_name" {
  description = "Reserved global static IP name for the platform ingress."
  value       = google_compute_global_address.platform_ingress.name
}

output "public_ingress_ip_address" {
  description = "Reserved global static IP address for the platform ingress."
  value       = google_compute_global_address.platform_ingress.address
}

output "cloud_armor_security_policy_name" {
  description = "Cloud Armor security policy attached to the public GKE ingress backends."
  value       = google_compute_security_policy.platform_edge.name
}
