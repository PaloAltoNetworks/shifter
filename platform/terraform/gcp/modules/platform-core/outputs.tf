output "network_name" {
  description = "Name of the platform VPC."
  value       = google_compute_network.platform.name
}

output "range_network_name" {
  description = "Name of the dedicated range VPC."
  value       = google_compute_network.range.name
}

output "range_network_id" {
  description = "Identifier of the dedicated range VPC."
  value       = google_compute_network.range.id
}

output "range_network_cidr" {
  description = "Base CIDR reserved for per-range subnet allocation."
  value       = var.range_network_cidr
}

output "range_network_region" {
  description = "Primary region for the dedicated range VPC."
  value       = var.region
}

output "portal_network_cidrs" {
  description = "Portal-side CIDRs that need connectivity into the range VPC."
  value       = local.portal_network_cidrs
}

output "gke_subnetwork_name" {
  description = "Name of the GKE subnetwork."
  value       = google_compute_subnetwork.gke.name
}

output "gke_cluster_name" {
  description = "Name of the GKE cluster."
  value       = google_container_cluster.platform.name
}

output "gke_cluster_location" {
  description = "Location of the GKE cluster."
  value       = google_container_cluster.platform.location
}

output "artifact_registry_repositories" {
  description = "Artifact Registry repositories by logical image role."
  value = {
    for name, repo in google_artifact_registry_repository.docker :
    name => repo.repository_id
  }
}

output "artifact_registry_image_roots" {
  description = "Artifact Registry image roots keyed by logical image role."
  value = {
    for name, repo in google_artifact_registry_repository.docker :
    name => "${var.artifact_registry_location}-docker.pkg.dev/${var.project_id}/${repo.repository_id}/${name}"
  }
}

output "assets_bucket_name" {
  description = "GCS bucket for shared platform assets."
  value       = google_storage_bucket.assets.name
}

output "public_ingress_ip_name" {
  description = "Reserved global static IP name for the platform ingress."
  value       = google_compute_global_address.platform_ingress.name
}

output "public_ingress_ip_address" {
  description = "Reserved global static IP address for the platform ingress."
  value       = google_compute_global_address.platform_ingress.address
}

output "public_hostname" {
  description = "Optional public hostname configured for the ingress."
  value       = local.normalized_public_hostname
}

output "managed_tls_enabled" {
  description = "Whether managed TLS is enabled for the ingress hostname."
  value       = var.enable_managed_tls
}

output "dns_managed_zone_name" {
  description = "Cloud DNS managed zone name used for the ingress record, if any."
  value       = var.dns_managed_zone_name
}

output "platform_events_topic_id" {
  description = "Shared Pub/Sub topic for platform lifecycle and experiment events."
  value       = google_pubsub_topic.platform_events.id
}

output "platform_event_subscriptions" {
  description = "Pub/Sub subscriptions keyed by worker role."
  value = {
    for name, subscription in google_pubsub_subscription.platform_events :
    name => subscription.id
  }
}

output "runtime_secret_ids" {
  description = "Secret Manager secret resource IDs for runtime secret bundles."
  value = {
    for name, secret in google_secret_manager_secret.runtime :
    name => secret.id
  }
}

output "workload_service_accounts" {
  description = "Workload service accounts by logical role."
  value = {
    for name, account in google_service_account.workload :
    name => account.email
  }
}

output "node_service_account_email" {
  description = "Service account email for GKE nodes."
  value       = google_service_account.gke_nodes.email
}

output "workload_identity_pool" {
  description = "GKE Workload Identity pool."
  value       = "${var.project_id}.svc.id.goog"
}

output "control_plane_database" {
  description = "Control-plane database connection metadata."
  value = {
    instance_name = google_sql_database_instance.platform.name
    private_ip    = google_sql_database_instance.platform.private_ip_address
    port          = 5432
    database_name = google_sql_database.platform.name
    user_name     = google_sql_user.platform.name
  }
}

output "control_plane_cache" {
  description = "Control-plane Redis connection metadata."
  value = {
    host = google_redis_instance.platform.host
    port = google_redis_instance.platform.port
  }
}

output "guacamole_database" {
  description = "Guacamole database connection metadata."
  value = {
    database_name = google_sql_database.guacamole.name
    user_name     = google_sql_user.guacamole.name
    host          = google_sql_database_instance.platform.private_ip_address
    port          = 5432
  }
}
