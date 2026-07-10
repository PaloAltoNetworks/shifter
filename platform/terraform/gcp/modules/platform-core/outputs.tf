output "network_name" {
  description = "Name of the platform VPC."
  value       = module.portal_vpc.network_name
}

output "range_network_name" {
  description = "Name of the dedicated range VPC."
  value       = module.range_vpc.range_network_name
}

output "range_network_id" {
  description = "Identifier of the dedicated range VPC."
  value       = module.range_vpc.range_network_id
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

output "gke_services_cidr" {
  description = "GKE service CIDR used by in-cluster clients to reach Kubernetes service IPs."
  value       = var.gke_services_cidr
}

output "gke_subnetwork_name" {
  description = "Name of the GKE subnetwork."
  value       = module.portal_vpc.gke_subnetwork_name
}

output "gke_cluster_name" {
  description = "Name of the GKE cluster."
  value       = module.portal_gke.gke_cluster_name
}

output "gke_cluster_location" {
  description = "Location of the GKE cluster."
  value       = module.portal_gke.gke_cluster_location
}

output "artifact_registry_repositories" {
  description = "Artifact Registry repositories by logical image role."
  value       = module.portal_artifact_registry.artifact_registry_repositories
}

output "artifact_registry_image_roots" {
  description = "Artifact Registry image roots keyed by logical image role."
  value       = module.portal_artifact_registry.artifact_registry_image_roots
}

output "assets_bucket_name" {
  description = "GCS bucket for shared platform assets."
  value       = module.portal_gcs.assets_bucket_name
}

output "terraform_state_bucket_name" {
  description = "Expected GCS bucket name for provisioner Terraform state."
  value       = "${var.project_id}-terraform-state"
}

output "public_ingress_ip_name" {
  description = "Reserved global static IP name for the platform ingress."
  value       = module.portal_ingress.public_ingress_ip_name
}

output "public_ingress_ip_address" {
  description = "Reserved global static IP address for the platform ingress."
  value       = module.portal_ingress.public_ingress_ip_address
}

output "cloud_armor_security_policy_name" {
  description = "Cloud Armor security policy attached to the public GKE ingress backends."
  value       = module.portal_ingress.cloud_armor_security_policy_name
}

output "identity_platform_api_key" {
  description = "Identity Platform web API key for the project."
  value       = module.portal_identity_platform.identity_platform_api_key
  sensitive   = true
}

output "identity_platform_project_id" {
  description = "Project ID backing the Identity Platform configuration."
  value       = var.project_id
}

output "identity_allowed_email_domain" {
  description = "Email domain enforced by the Identity Platform blocking function and the portal allow-list."
  value       = var.identity_allowed_email_domain
}

output "identity_allowed_emails" {
  description = "Explicit allow-listed emails (beyond the domain) enforced by the Identity Platform blocking function and the portal."
  value       = var.identity_allowed_emails
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
  value       = module.portal_messaging.platform_events_topic_id
}

output "platform_event_subscriptions" {
  description = "Pub/Sub subscriptions keyed by worker role."
  value       = module.portal_messaging.platform_event_subscriptions
}

output "runtime_secret_ids" {
  description = "Secret Manager secret resource IDs for runtime secret bundles."
  value       = module.portal_secrets.runtime_secret_ids
}

output "email_config" {
  description = <<-EOT
    Transactional-email runtime config consumed by scripts/gcp/render_runtime_env.py
    (PLAT-002, #671). null when email_backend is empty (console fallback). When set,
    api_key_secret_id references the unseeded Secret Manager secret the operator
    populates with the ESP API key; the key value is never part of this output.
  EOT
  value = var.email_backend == "" ? null : {
    backend           = var.email_backend
    from_email        = var.email_from_address
    sender_domain     = var.email_sender_domain
    api_key_secret_id = module.portal_secrets.runtime_secret_ids["email"]
  }
}

output "workload_service_accounts" {
  description = "Workload service accounts by logical role."
  value       = module.portal_iam.workload_service_accounts
}

output "node_service_account_email" {
  description = "Service account email for GKE nodes."
  value       = module.portal_iam.node_service_account_email
}

output "workload_identity_pool" {
  description = "GKE Workload Identity pool."
  value       = module.portal_gke.workload_identity_pool
}

output "control_plane_database" {
  description = "Control-plane database connection metadata."
  value       = module.portal_cloud_sql.control_plane_database
}

output "control_plane_cache" {
  description = "Control-plane Redis connection metadata. tls_enabled signals to the runtime renderer that the channel layer must build a rediss:// host; the AUTH token itself is held in Secret Manager and surfaced via `runtime_secret_ids[\"redis\"]` (ADR-008-R6)."
  value       = module.portal_redis.control_plane_cache
}

output "guacamole_database" {
  description = "Guacamole database connection metadata."
  value       = module.portal_cloud_sql.guacamole_database
}
