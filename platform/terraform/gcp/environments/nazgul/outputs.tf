output "network_name" {
  description = "Name of the GCP platform VPC."
  value       = module.platform_core.network_name
}

output "dynamic_secret_project_id" {
  description = "Deployment-scoped project that owns provisioner-created range secrets."
  value       = module.platform_core.dynamic_secret_project_id
}

output "provisioner_static_secret_refs" {
  description = "Exact operator-created GDC/Vertex secret references published to the provisioner runtime."
  value       = module.platform_core.provisioner_static_secret_refs
}

output "range_network_name" {
  description = "Name of the dedicated GCP range VPC."
  value       = module.platform_core.range_network_name
}

output "range_network_id" {
  description = "Identifier of the dedicated GCP range VPC."
  value       = module.platform_core.range_network_id
}

output "range_network_cidr" {
  description = "Base CIDR reserved for per-range subnet allocation."
  value       = module.platform_core.range_network_cidr
}

output "range_network_region" {
  description = "Primary region for the dedicated GCP range VPC."
  value       = module.platform_core.range_network_region
}

output "portal_network_cidrs" {
  description = "Provisioner/management-source CIDRs (provisioner pod range) for per-range host-management ingress and the OpenVPN health probe (#1711)."
  value       = module.platform_core.portal_network_cidrs
}

output "access_network_cidrs" {
  description = "Access-workload source CIDRs (access pod range) for per-range participant SSH/RDP ingress; portal + guacd only (#1711, ADR-039-R9)."
  value       = module.platform_core.access_network_cidrs
}

output "gke_services_cidr" {
  description = "GKE service CIDR used by in-cluster clients to reach Kubernetes service IPs."
  value       = module.platform_core.gke_services_cidr
}

output "gke_master_ipv4_cidr" {
  description = "GKE control-plane (master) CIDR. Under Dataplane V2 (Cilium), egress to the Kubernetes API is enforced on the translated control-plane endpoint, not the services-CIDR ClusterIP, so in-cluster API clients must allow this range."
  value       = module.platform_core.gke_master_ipv4_cidr
}

output "gke_pods_cidr" {
  description = "GKE pod CIDR. Non-secret; source for the range-escape validation config (#1347)."
  value       = module.platform_core.gke_pods_cidr
}

output "gke_nodes_cidr" {
  description = "GKE node subnet CIDR. Non-secret; source for the range-escape validation config (#1347)."
  value       = module.platform_core.gke_nodes_cidr
}

output "gke_cluster_name" {
  description = "Name of the GKE cluster."
  value       = module.platform_core.gke_cluster_name
}

output "gke_cluster_location" {
  description = "Location of the GKE cluster."
  value       = module.platform_core.gke_cluster_location
}

output "artifact_registry_repositories" {
  description = "Artifact Registry repositories for the environment."
  value       = module.platform_core.artifact_registry_repositories
}

output "artifact_registry_image_roots" {
  description = "Artifact Registry image roots for the environment."
  value       = module.platform_core.artifact_registry_image_roots
}

output "assets_bucket_name" {
  description = "Shared GCS bucket for platform uploads and agent artifacts."
  value       = module.platform_core.assets_bucket_name
}

output "ctf_content_bucket_name" {
  description = "Private bucket configured for digest-pinned native CTF content bundles."
  value       = var.ctf_content_bucket_name
}

output "terraform_state_bucket_name" {
  description = "GCS bucket name for provisioner Terraform state."
  value       = module.platform_core.terraform_state_bucket_name
}

output "public_ingress_ip_name" {
  description = "Reserved global static IP name for the GKE ingress."
  value       = module.platform_core.public_ingress_ip_name
}

output "public_ingress_ip_address" {
  description = "Reserved global static IP address for the GKE ingress."
  value       = module.platform_core.public_ingress_ip_address
}

output "cloud_armor_security_policy_name" {
  description = "Cloud Armor security policy attached to the public ingress backends."
  value       = module.platform_core.cloud_armor_security_policy_name
}

output "identity_platform_api_key" {
  description = "Identity Platform web API key for the environment."
  value       = module.platform_core.identity_platform_api_key
  sensitive   = true
}

output "identity_platform_project_id" {
  description = "Project ID backing Identity Platform for this environment."
  value       = module.platform_core.identity_platform_project_id
}

output "identity_allowed_email_domain" {
  description = "Email domain enforced by the Identity Platform blocking function and the portal allow-list."
  value       = module.platform_core.identity_allowed_email_domain
}

output "identity_allowed_emails" {
  description = "Explicit allow-listed emails enforced by the Identity Platform blocking function and the portal."
  value       = module.platform_core.identity_allowed_emails
}

output "public_hostname" {
  description = "Optional public hostname configured for the ingress."
  value       = module.platform_core.public_hostname
}

output "managed_tls_enabled" {
  description = "Whether managed TLS is enabled for the ingress hostname."
  value       = module.platform_core.managed_tls_enabled
}

output "dns_managed_zone_name" {
  description = "Cloud DNS managed zone name used for the ingress record, if any."
  value       = module.platform_core.dns_managed_zone_name
}

output "platform_events_topic_id" {
  description = "Shared Pub/Sub topic for platform events."
  value       = module.platform_core.platform_events_topic_id
}

output "platform_event_subscriptions" {
  description = "Pub/Sub subscriptions for platform workers."
  value       = module.platform_core.platform_event_subscriptions
}

output "runtime_secret_ids" {
  description = "Secret Manager secret resource IDs for runtime bundles."
  value       = module.platform_core.runtime_secret_ids
}

output "email_config" {
  description = "Transactional-email runtime config for render_runtime_env.py (PLAT-002, #671); null when email is unconfigured."
  value       = module.platform_core.email_config
}

output "control_plane_database" {
  description = "Control-plane database connection metadata."
  value       = module.platform_core.control_plane_database
}

output "control_plane_cache" {
  description = "Control-plane Redis connection metadata."
  value       = module.platform_core.control_plane_cache
}

output "guacamole_database" {
  description = "Guacamole database connection metadata."
  value       = module.platform_core.guacamole_database
}

output "workload_service_accounts" {
  description = "Workload service accounts for the environment."
  value       = module.platform_core.workload_service_accounts
}

# The GitHub OIDC provider + packer build service account (the CI auth identity)
# are outputs of the foundational root platform/terraform/gcp/global/cicd-oidc,
# not this platform root -- so a platform destroy never removes them. Read
# Read GCP_WORKLOAD_IDENTITY_PROVIDER and the explicit build/validate/deploy/
# destroy service-account values from that root's outputs.

output "range_host_service_account_email" {
  description = "GCE range host SA email for hosts that need cloud APIs; set GCP_RANGE_HOST_SERVICE_ACCOUNT_EMAIL for a same-project range cell."
  value       = module.platform_core.range_host_service_account_email
}

output "range_vertex_service_account_email" {
  description = "GCE range Vertex SA email; set GCP_RANGE_VERTEX_SERVICE_ACCOUNT_EMAIL to this for a same-project range cell."
  value       = module.platform_core.range_vertex_service_account_email
}
