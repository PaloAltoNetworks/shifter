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
