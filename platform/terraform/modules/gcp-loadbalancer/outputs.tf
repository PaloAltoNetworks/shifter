output "static_ip_address" {
  description = "Static external IP address (point your DNS A record here)"
  value       = google_compute_global_address.portal.address
}

output "static_ip_name" {
  description = "Static IP resource name (used in GKE Ingress annotation: kubernetes.io/ingress.global-static-ip-name)"
  value       = google_compute_global_address.portal.name
}

output "ssl_certificate_name" {
  description = "Managed SSL certificate name (used in GKE Ingress annotation: networking.gke.io/managed-certificates)"
  value       = google_compute_managed_ssl_certificate.portal.name
}

output "security_policy_name" {
  description = "Cloud Armor security policy name (used in GKE BackendConfig)"
  value       = google_compute_security_policy.portal.name
}
