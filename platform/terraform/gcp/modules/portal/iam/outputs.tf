output "node_service_account_email" {
  description = "Service account email for GKE nodes."
  value       = google_service_account.gke_nodes.email
}

output "workload_service_accounts" {
  description = "Workload service accounts by logical role."
  value = {
    for name, account in google_service_account.workload :
    name => account.email
  }
}

output "range_host_service_account_email" {
  description = "Email of the GCE range host service account, attached only to hosts that need cloud APIs."
  value       = google_service_account.range_host.email
}

output "range_vertex_service_account_email" {
  description = "Email of the GCE range Vertex service account (per-range key minting)."
  value       = google_service_account.range_vertex.email
}
