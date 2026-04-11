variable "project_id" {
  description = "GCP project ID for gcp-dev."
  type        = string
}

variable "environment" {
  description = "Environment name."
  type        = string
  default     = "gcp-dev"
}

variable "region" {
  description = "Primary GCP region."
  type        = string
}

variable "artifact_registry_location" {
  description = "Artifact Registry location."
  type        = string
}

variable "gke_release_channel" {
  description = "GKE release channel."
  type        = string
  default     = "REGULAR"
}

variable "gke_subnet_cidr" {
  description = "Primary subnet CIDR for GKE nodes."
  type        = string
}

variable "gke_pods_cidr" {
  description = "Secondary range for GKE pods."
  type        = string
}

variable "gke_services_cidr" {
  description = "Secondary range for GKE services."
  type        = string
}

variable "gke_master_ipv4_cidr" {
  description = "Private control-plane CIDR for GKE."
  type        = string
}

variable "gke_master_authorized_cidrs" {
  description = "CIDR blocks allowed to reach the public GKE control-plane endpoint."
  type        = list(string)
  default     = []
}

variable "range_network_cidr" {
  description = "Base CIDR reserved for per-range subnet allocation."
  type        = string
}

variable "web_machine_type" {
  description = "Machine type for the web node pool."
  type        = string
  default     = "e2-standard-4"
}

variable "worker_machine_type" {
  description = "Machine type for the worker node pool."
  type        = string
  default     = "e2-standard-4"
}

variable "provisioner_machine_type" {
  description = "Machine type for the provisioner node pool."
  type        = string
  default     = "n2-standard-8"
}

variable "web_node_count" {
  description = "Desired size for the web node pool."
  type        = number
  default     = 1
}

variable "worker_node_count" {
  description = "Desired size for the worker node pool."
  type        = number
  default     = 1
}

variable "provisioner_node_count" {
  description = "Desired size for the provisioner node pool."
  type        = number
  default     = 1
}

variable "cloud_sql_database_version" {
  description = "Cloud SQL PostgreSQL version for the control-plane database."
  type        = string
  default     = "POSTGRES_15"
}

variable "cloud_sql_tier" {
  description = "Cloud SQL machine tier for the control-plane database."
  type        = string
  default     = "db-custom-1-3840"
}

variable "cloud_sql_disk_size_gb" {
  description = "Cloud SQL disk size in GiB."
  type        = number
  default     = 20
}

variable "cloud_sql_database_name" {
  description = "Default PostgreSQL database name for the control plane."
  type        = string
  default     = "shifter"
}

variable "cloud_sql_user_name" {
  description = "Application PostgreSQL username for the control plane."
  type        = string
  default     = "shifter"
}

variable "redis_tier" {
  description = "Memorystore tier for the control-plane Redis instance."
  type        = string
  default     = "BASIC"
}

variable "redis_memory_size_gb" {
  description = "Memorystore capacity in GiB."
  type        = number
  default     = 1
}

variable "public_hostname" {
  description = "Optional public hostname for the GKE ingress."
  type        = string
  default     = ""
}

variable "enable_managed_tls" {
  description = "Whether the GKE ingress should use a Google-managed certificate when a hostname is configured."
  type        = bool
  default     = false
}

variable "create_dns_managed_zone" {
  description = "Whether to create a Cloud DNS managed zone for the configured public hostname."
  type        = bool
  default     = false
}

variable "dns_managed_zone_name" {
  description = "Name of the Cloud DNS managed zone to create or update."
  type        = string
  default     = ""
}

variable "dns_zone_dns_name" {
  description = "DNS suffix for the optional Cloud DNS managed zone, for example 'example.com.'."
  type        = string
  default     = ""
}

variable "dns_record_ttl" {
  description = "TTL in seconds for the optional ingress A record."
  type        = number
  default     = 300
}
