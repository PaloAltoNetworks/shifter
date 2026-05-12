# terraform.tfvars — example values for OSS deployers.
# Copy this file to terraform.tfvars (gitignored) and replace example.com placeholders
# with your real domains / email senders / alarm destinations before
# `terraform apply`. Secrets remain in AWS Secrets Manager / GCP Secret Manager,
# never in tfvars.

# REPLACE: your GCP project id (no default — this must be your project).
project_id                 = "REPLACE_WITH_YOUR_GCP_PROJECT_ID"
environment                = "gcp-dev"
region                     = "us-central1"
artifact_registry_location = "us-central1"
gke_release_channel        = "REGULAR"

gke_subnet_cidr      = "10.40.0.0/20"
gke_pods_cidr        = "10.44.0.0/16"
gke_services_cidr    = "10.45.0.0/20"
gke_master_ipv4_cidr = "172.16.0.0/28"
# REPLACE: list of /32 CIDRs from which you'll run `gcloud`/`kubectl` against
# the GKE control plane (your bootstrap workstation, CI runner egress, etc.).
# Leaving this empty closes the GKE control plane to the public internet.
gke_master_authorized_cidrs = []
range_network_cidr          = "10.50.0.0/16"

web_machine_type         = "e2-standard-4"
worker_machine_type      = "e2-standard-4"
provisioner_machine_type = "n2-standard-8"

web_node_count         = 1
worker_node_count      = 1
provisioner_node_count = 1

cloud_sql_database_version  = "POSTGRES_15"
cloud_sql_tier              = "db-custom-1-3840"
cloud_sql_availability_type = "ZONAL"
cloud_sql_disk_size_gb      = 20
cloud_sql_database_name     = "shifter"
cloud_sql_user_name         = "shifter"

# Memorystore tier: STANDARD_HA is the production high-availability posture.
# AUTH and SERVER_AUTHENTICATION TLS are enforced unconditionally by the
# platform-core module regardless of tier (ADR-008-R6, #963).
redis_tier           = "STANDARD_HA"
redis_memory_size_gb = 1

public_hostname         = "shifter.example.com"
enable_managed_tls      = true
create_dns_managed_zone = false
dns_managed_zone_name   = ""
dns_zone_dns_name       = ""
dns_record_ttl          = 300

# REPLACE: the email domain permitted to sign in via Identity Platform's
# beforeCreate allowlist. Use only a domain your tenancy owns; do NOT ship a
# third-party domain in an example. The runtime renderer rejects a blank value
# so the placeholder below is loud-and-broken until you replace it.
identity_allowed_email_domain = "REPLACE_WITH_YOUR_TENANCY_DOMAIN.example"
identity_allowed_emails       = []
