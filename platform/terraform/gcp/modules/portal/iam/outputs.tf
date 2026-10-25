output "node_service_account_email" {
  description = "Service account email for GKE nodes."
  value       = google_service_account.gke_nodes.email
  # platform-core's portal_gke orders after the node SA via this output. Add the
  # deployer-actAs binding to that ordering so the node pools are never created
  # before the deploy SA can actAs the node SA. Safe (unlike depending on the
  # whole iam module): this binding is cluster-independent and cannot deadlock.
  depends_on = [google_service_account_iam_member.deploy_act_as_gke_nodes]
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

output "native_database_users" {
  description = "Native PostgreSQL login identifiers by workload, without credential payloads."
  value       = { for workload, user in google_sql_user.native : workload => user.name }
}
