output "endpoint" {
  description = "Static address every participant profile connects to (UDP 1194)."
  value       = google_compute_address.endpoint.address
}

output "subnet_cidr" {
  description = "Pool source network; each OpenVPN range admits it to its target node."
  value       = google_compute_subnetwork.pool.ip_cidr_range
}

output "service_account_email" {
  description = "Pool identity the portal admits on the VPN control API."
  value       = google_service_account.pool.email
}

output "service_account_id" {
  description = "Immutable numeric subject of the pool identity."
  value       = google_service_account.pool.unique_id
}

output "control_audience" {
  description = "Audience of the pool's identity tokens."
  value       = local.control_audience
}

output "issuer_secret" {
  description = "Tenant CA secret (provisioner only)."
  value       = google_secret_manager_secret.pool["issuer"].id
}

output "server_secret" {
  description = "Pool server identity secret (pool only)."
  value       = google_secret_manager_secret.pool["server"].id
}

output "release_secret" {
  description = "Release record: the image digest pool servers run."
  value       = google_secret_manager_secret.pool["release"].id
}

output "image_root" {
  description = "Image root the release record must name."
  value       = local.image_root
}

output "instance_group" {
  description = "Regional instance group name, for rolling replacement at deploy."
  value       = google_compute_region_instance_group_manager.pool.name
}

output "backend_service" {
  description = "Load balancer backend service, for the deploy-time health check."
  value       = google_compute_region_backend_service.pool.name
}

output "subnetwork_name" {
  description = "#2535: Terraform-owned pool subnet in the range VPC; the telemetry readback gates it."
  value       = google_compute_subnetwork.pool.name
}

output "nat_router_name" {
  description = "#2535: Terraform-owned pool NAT router in the range VPC; the telemetry readback gates it."
  value       = google_compute_router.pool.name
}
