variable "project_id" {
  description = "GCP project ID for the environment."
  type        = string
}

variable "environment" {
  description = "Environment name."
  type        = string
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
  description = "Secondary range for GKE pods (web + worker node pools)."
  type        = string
}

variable "gke_services_cidr" {
  description = "Secondary range for GKE services."
  type        = string
}

variable "gke_provisioner_pods_cidr" {
  description = "Dedicated secondary pod range for the provisioner node pool. Isolating the provisioner's pod IPs from the shared pods range lets the range-VPC firewall scope admin-port ingress to just the provisioner — a compromised portal/worker/guacamole pod sourced from the shared pods range no longer satisfies range-allow-platform-provisioner (ADR-008-R4, #959)."
  type        = string
  default     = "10.46.0.0/20"
}

variable "gke_master_ipv4_cidr" {
  description = "Private control-plane CIDR for GKE."
  type        = string
}

variable "gke_master_authorized_cidrs" {
  description = "CIDR blocks allowed to reach the public GKE control-plane endpoint. Required: the cluster runs with enable_private_endpoint = false, so master_authorized_networks_config is the only network-level restriction on the public Kubernetes API server (ADR-008; docs/architecture/gke-control-plane-access-preflight.md). The environment root must supply at least one CIDR."
  type        = list(string)

  # Fail closed: an empty, malformed, or world-open (/0) allowlist would expose
  # the public API server to the entire internet. This is the Terraform-layer
  # backstop for the bootstrap preflight
  # (scripts/bootstrap/deploy.py::validate_gcp_control_plane_security_inputs);
  # both gates express the same contract from the parsed prefix:
  #   1. cidrhost(cidr, 0) — entry parses as a CIDR (rejects bare IPs, garbage,
  #      bad octets, bad prefixes).
  #   2. an explicit /N suffix is present.
  #   3. the parsed prefix length is > 0 (so /0 is rejected from the prefix
  #      number, not by string-suffix matching against one spelling).
  validation {
    condition = length(var.gke_master_authorized_cidrs) > 0 && alltrue([
      for cidr in var.gke_master_authorized_cidrs :
      can(cidrhost(cidr, 0))
      && can(regex("/[0-9]+$", cidr))
      && tonumber(regex("/([0-9]+)$", cidr)[0]) > 0
    ])
    error_message = "gke_master_authorized_cidrs must contain at least one CIDR; every entry must be a valid CIDR with an explicit /N suffix (e.g. 203.0.113.10/32), and no entry may be a /0 (world-open) range. The GKE control-plane endpoint is public (enable_private_endpoint = false), so an empty or world-open allowlist would expose the Kubernetes API server to the entire internet. Set it from the environment root (see ADR-008 and docs/architecture/gke-control-plane-access-preflight.md); if a private endpoint is intended, change enable_private_endpoint and relax this rule together."
  }
}

variable "range_network_cidr" {
  description = "Base CIDR reserved for Compute Engine range subnet allocation."
  type        = string
}

variable "gke_pods_secondary_range_name" {
  description = "Secondary range name for GKE pods."
  type        = string
  default     = "gke-pods"
}

variable "gke_services_secondary_range_name" {
  description = "Secondary range name for GKE services."
  type        = string
  default     = "gke-services"
}

variable "gke_provisioner_pods_secondary_range_name" {
  description = "Secondary range name on the GKE subnet for the provisioner node pool's dedicated pod range."
  type        = string
  default     = "gke-provisioner-pods"
}

variable "private_service_range_prefix_length" {
  description = "Prefix length for the reserved service networking range."
  type        = number
  default     = 20
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

variable "cloud_sql_availability_type" {
  description = "Cloud SQL availability type. Use REGIONAL for production HA and ZONAL for lower-cost development."
  type        = string
  default     = "REGIONAL"

  validation {
    condition     = contains(["REGIONAL", "ZONAL"], var.cloud_sql_availability_type)
    error_message = "cloud_sql_availability_type must be either REGIONAL or ZONAL."
  }
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

variable "cloud_sql_deletion_protection" {
  description = "Enable Cloud SQL deletion protection on the platform instance. Default true; only set false for intentionally disposable environments (the platform database is durable control-plane state)."
  type        = bool
  default     = true
}

variable "redis_tier" {
  description = "Memorystore tier for the control-plane Redis instance. Default STANDARD_HA: the platform cache is shared multi-pod state and the production posture is high-availability replication. AUTH and TLS posture are independent of tier — the module enables them unconditionally — so a future disposable environment can opt into BASIC by overriding this variable without weakening the security contract."
  type        = string
  default     = "STANDARD_HA"

  validation {
    condition     = contains(["BASIC", "STANDARD_HA"], var.redis_tier)
    error_message = "redis_tier must be one of: BASIC, STANDARD_HA."
  }
}

variable "redis_memory_size_gb" {
  description = "Memorystore capacity in GiB."
  type        = number
  default     = 1
}

variable "public_hostname" {
  description = "Optional public hostname for the platform ingress."
  type        = string
  default     = ""
}

variable "enable_managed_tls" {
  description = "Whether to use a Google-managed certificate for the public hostname."
  type        = bool
  default     = false
}

variable "create_dns_managed_zone" {
  description = "Whether to create a public Cloud DNS managed zone for the ingress hostname."
  type        = bool
  default     = false
}

variable "dns_managed_zone_name" {
  description = "Name of the Cloud DNS managed zone to create or update."
  type        = string
  default     = ""
}

variable "dns_zone_dns_name" {
  description = "DNS suffix for the optional Cloud DNS managed zone."
  type        = string
  default     = ""
}

variable "dns_record_ttl" {
  description = "TTL in seconds for the optional ingress A record. Use 60 for production to enable fast failover; 300 is acceptable for dev/staging."
  type        = number
  default     = 60
}

variable "labels" {
  description = "Additional labels to apply to GCP resources."
  type        = map(string)
  default     = {}
}

variable "identity_allowed_email_domain" {
  description = "Corporate email domain allowed to self-register in Identity Platform."
  type        = string
  default     = "paloaltonetworks.com"
}

variable "identity_allowed_emails" {
  description = "Explicit non-domain email addresses allowed to self-register in Identity Platform."
  type        = list(string)
  default     = []
}

variable "range_provisioner_ports" {
  description = "TCP ports the platform provisioner is allowed to reach on the range VPC. Used to construct the range-allow-platform-provisioner firewall rule. The range VPC otherwise denies all ingress (ADR-008-R4)."
  type        = list(number)
  # Provisioner-to-range protocols today: SSH (22) for Linux range VMs,
  # RDP (3389) for Windows DC, and Guacamole websocket port (8080) for
  # remote display when proxied from the platform side. Update the list
  # when a new provisioner protocol is introduced.
  default = [22, 3389, 8080]

  validation {
    condition     = length(var.range_provisioner_ports) > 0
    error_message = "range_provisioner_ports must list at least one TCP port; an empty list would leave the provisioner unable to reach the range VPC."
  }

  validation {
    condition     = alltrue([for p in var.range_provisioner_ports : p >= 1 && p <= 65535])
    error_message = "range_provisioner_ports entries must be in the inclusive range [1, 65535]."
  }
}

variable "operator_admin_cidrs" {
  description = "Optional CIDR list authorized for break-glass direct SSH onto platform GKE nodes and range VMs. This is a direct-access allowlist (source CIDR matched at the VPC firewall), NOT an IAP rule — IAP TCP forwarding presents traffic from Google's fixed proxy range and is handled separately. Default empty: dev relies on Workload Identity and IAM-only operator paths. Entries must be valid CIDR blocks with an IPv4 prefix of /24 or narrower (or IPv6 /96 or narrower); broad ranges are rejected so a misconfigured environment cannot accidentally open SSH to internet-scale sources past the broader deny rule."
  type        = list(string)
  default     = []

  # Parse the CIDR with cidrhost() — that fails for bare IPs, malformed
  # entries, and unparseable prefixes — and then require a prefix length
  # that is meaningfully narrow. The pattern matches the
  # gke_master_authorized_cidrs validation in this same module.
  #
  # Prefix-breadth policy: IPv4 must be /24 or longer, IPv6 must be /96
  # or longer. This prevents both literal `0.0.0.0/0`/`::/0` AND broad
  # equivalents like `0.0.0.0/1` + `128.0.0.0/1` from satisfying the
  # rule. Operator workstations and small office subnets fit easily;
  # provider ASNs / continent-sized ranges do not.
  validation {
    condition = alltrue([
      for cidr in var.operator_admin_cidrs : (
        can(cidrhost(cidr, 0))
        && can(regex("/[0-9]+$", cidr))
        && (
          # IPv4 path: cidrnetmask succeeds only for IPv4. Require /24+.
          (can(cidrnetmask(cidr)) && tonumber(regex("/([0-9]+)$", cidr)[0]) >= 24)
          ||
          # IPv6 path: cidrnetmask refuses IPv6, but cidrhost succeeded
          # above. Require /96+ as the IPv6 equivalent of a narrow subnet.
          (!can(cidrnetmask(cidr)) && tonumber(regex("/([0-9]+)$", cidr)[0]) >= 96)
        )
      )
    ])
    error_message = "operator_admin_cidrs entries must be valid CIDRs with an explicit /N suffix (IPv4 must be /24 or longer; IPv6 must be /96 or longer). Direct break-glass SSH is never opened to broad external ranges; route wider operator access through IAP / OS Login instead (ADR-008-R4)."
  }
}
