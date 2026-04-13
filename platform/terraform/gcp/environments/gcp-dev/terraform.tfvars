project_id                 = "prod-rwctxzl6shxk"
environment                = "gcp-dev"
region                     = "us-central1"
artifact_registry_location = "us-central1"
gke_release_channel        = "REGULAR"

gke_subnet_cidr      = "10.40.0.0/20"
gke_pods_cidr        = "10.44.0.0/16"
gke_services_cidr    = "10.45.0.0/20"
gke_master_ipv4_cidr = "172.16.0.0/28"
gke_master_authorized_cidrs = [
  # Current admin egress from the WSL workstation running bootstrap.
  # Update this if the operator egress IP changes.
  "173.181.31.170/32",
]
range_network_cidr = "10.50.0.0/16"

web_machine_type         = "e2-standard-4"
worker_machine_type      = "e2-standard-4"
provisioner_machine_type = "n2-standard-8"

web_node_count         = 1
worker_node_count      = 1
provisioner_node_count = 1

cloud_sql_database_version = "POSTGRES_15"
cloud_sql_tier             = "db-custom-1-3840"
cloud_sql_disk_size_gb     = 20
cloud_sql_database_name    = "shifter"
cloud_sql_user_name        = "shifter"

redis_tier           = "BASIC"
redis_memory_size_gb = 1

public_hostname         = "shifter.keplerops.com"
enable_managed_tls      = true
create_dns_managed_zone = false
dns_managed_zone_name   = ""
dns_zone_dns_name       = ""
dns_record_ttl          = 300

identity_allowed_email_domain = "paloaltonetworks.com"
identity_allowed_emails       = []
monitoring_alert_email        = "bedwards@paloaltonetworks.com"
