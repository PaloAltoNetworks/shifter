output "range_network_id" {
  description = "Identifier of the dedicated range VPC."
  value       = google_compute_network.range.id
}

output "range_network_name" {
  description = "Name of the dedicated range VPC."
  value       = google_compute_network.range.name
}

output "bridge_nat_router_names" {
  description = "#2535: Terraform-owned migration-bridge NAT routers on the range VPC (primary region first)."
  value = concat(
    google_compute_router.range_nat[*].name,
    [for region in sort(keys(google_compute_router.range_nat_extra)) : google_compute_router.range_nat_extra[region].name],
  )
}
