resource "google_compute_network" "platform" {
  name                    = "${var.name_prefix}-platform"
  project                 = var.project_id
  auto_create_subnetworks = false
}

resource "google_compute_subnetwork" "gke" {
  name                     = "${var.name_prefix}-gke"
  project                  = var.project_id
  region                   = var.region
  network                  = google_compute_network.platform.id
  ip_cidr_range            = var.gke_subnet_cidr
  private_ip_google_access = true

  log_config {
    aggregation_interval = "INTERVAL_5_SEC"
    flow_sampling        = 0.5
    metadata             = "INCLUDE_ALL_METADATA"
  }

  secondary_ip_range {
    range_name    = var.gke_pods_secondary_range_name
    ip_cidr_range = var.gke_pods_cidr
  }

  secondary_ip_range {
    range_name    = var.gke_services_secondary_range_name
    ip_cidr_range = var.gke_services_cidr
  }

  secondary_ip_range {
    range_name    = var.gke_provisioner_pods_secondary_range_name
    ip_cidr_range = var.gke_provisioner_pods_cidr
  }

  # Dedicated access-workload pod range (#1711): portal + guacd pods receive
  # alias IPs from this range on the exclusive access node pool, so the per-range
  # GCE ingress firewall can scope participant SSH/RDP to just these workloads
  # instead of the broad platform pod range. Disjoint from every other range.
  secondary_ip_range {
    range_name    = var.gke_access_pods_secondary_range_name
    ip_cidr_range = var.gke_access_pods_cidr
  }
}

resource "google_compute_router" "nat" {
  name    = "${var.name_prefix}-nat"
  project = var.project_id
  region  = var.region
  network = google_compute_network.platform.id
}

resource "google_compute_address" "nat" {
  name         = "${var.name_prefix}-nat-egress"
  project      = var.project_id
  region       = var.region
  address_type = "EXTERNAL"
}

resource "google_compute_router_nat" "nat" {
  name                               = "${var.name_prefix}-nat"
  project                            = var.project_id
  region                             = var.region
  router                             = google_compute_router.nat.name
  nat_ip_allocate_option             = "MANUAL_ONLY"
  nat_ips                            = [google_compute_address.nat.self_link]
  source_subnetwork_ip_ranges_to_nat = "ALL_SUBNETWORKS_ALL_IP_RANGES"

  # The whole platform (GKE nodes + every pod) egresses to the PUBLIC googleapis
  # endpoints through this NAT (there is no private-googleapis DNS path in this
  # VPC). A full rollout is a thundering herd: every pod opens gRPC connections
  # to Secret Manager and other googleapis IPs at once, and crashloop churn holds
  # source ports in TIME_WAIT. The default 64 static ports/VM exhaust under that
  # burst, so connections are dropped ("tcp handshaker shutdown" / connect
  # timeouts) and the Python pods crashloop on runtime-secret fetch. Enable
  # dynamic port allocation so the NAT scales ports per VM up to max under load
  # (requires endpoint-independent mapping OFF, which is the default here).
  enable_dynamic_port_allocation = true
  min_ports_per_vm               = 64
  max_ports_per_vm               = 32768
}

resource "google_compute_firewall" "platform_deny_external_ssh_rdp" {
  name        = "${var.name_prefix}-platform-deny-external-ssh-rdp"
  project     = var.project_id
  network     = google_compute_network.platform.name
  description = "ADR-008-R4: SSH/RDP from 0.0.0.0/0 is never allowed into the platform VPC."
  direction   = "INGRESS"
  priority    = 900

  source_ranges = ["0.0.0.0/0"]

  deny {
    protocol = "tcp"
    ports    = ["22", "3389"]
  }
}

resource "google_compute_firewall" "platform_allow_gke_health_checks" {
  name        = "${var.name_prefix}-platform-allow-gke-health-checks"
  project     = var.project_id
  network     = google_compute_network.platform.name
  description = "ADR-008-R4: Google LB health-check ranges reach GKE nodes; required for backend probes."
  direction   = "INGRESS"
  priority    = 1000

  source_ranges = [
    "35.191.0.0/16",
    "130.211.0.0/22",
  ]

  target_tags = ["gke"]

  allow {
    protocol = "tcp"
    ports    = ["80", "443", "8000", "8080", "30000-32767"]
  }
}

resource "google_compute_firewall" "platform_allow_operator_admin_ssh" {
  count = length(var.operator_admin_cidrs) > 0 ? 1 : 0

  name        = "${var.name_prefix}-platform-allow-operator-admin-ssh"
  project     = var.project_id
  network     = google_compute_network.platform.name
  description = "ADR-008-R4: break-glass direct SSH onto GKE platform nodes from the operator-admin CIDR allowlist (not IAP)."
  direction   = "INGRESS"
  priority    = 800

  source_ranges = var.operator_admin_cidrs
  target_tags   = ["gke"]

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }
}

resource "google_compute_global_address" "services" {
  name          = "${var.name_prefix}-services"
  project       = var.project_id
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = var.private_service_range_prefix_length
  network       = google_compute_network.platform.id
}

resource "google_service_networking_connection" "services" {
  network                 = google_compute_network.platform.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.services.name]
}

# Private Google Access DNS for the platform network. The access node pool is
# containment-isolated from public internet egress (#1711/#1295), so platform
# pods that land there (e.g. portal-web, which must sit in the access pod range to
# dial range guests - ADR-039-R9) cannot reach the PUBLIC googleapis endpoints.
# They can reach the private.googleapis.com VIP (199.36.153.8/30), and the
# platform NetworkPolicy allow-platform-google-apis-egress only permits that VIP.
# Without this zone platform pods resolve *.googleapis.com to public IPs and fail
# (Secret Manager fetch times out on the access pool). Resolve *.googleapis.com to
# the VIP so ALL platform pods use Private Google Access, matching the range VPC
# (modules/range/vpc) and the egress policy. The subnet already has
# private_ip_google_access = true; the explicit route pins the VIP to Google's
# fabric rather than the Cloud NAT default route.
resource "google_compute_route" "platform_private_googleapis" {
  name             = "${var.name_prefix}-platform-private-googleapis"
  project          = var.project_id
  network          = google_compute_network.platform.name
  description      = "Private Google Access: route the private.googleapis.com VIP over Google's internal fabric for platform pods."
  dest_range       = "199.36.153.8/30"
  next_hop_gateway = "default-internet-gateway"
  priority         = 1000
}

resource "google_dns_managed_zone" "platform_private_googleapis" {
  name        = "${var.name_prefix}-platform-googleapis"
  project     = var.project_id
  dns_name    = "googleapis.com."
  description = "Private Google Access: resolve *.googleapis.com to the private.googleapis.com VIP for platform pods."

  visibility = "private"

  private_visibility_config {
    networks {
      network_url = google_compute_network.platform.id
    }
  }
}

resource "google_dns_record_set" "platform_private_googleapis_a" {
  project      = var.project_id
  managed_zone = google_dns_managed_zone.platform_private_googleapis.name
  name         = "private.googleapis.com."
  type         = "A"
  ttl          = 300
  rrdatas      = ["199.36.153.8", "199.36.153.9", "199.36.153.10", "199.36.153.11"]
}

resource "google_dns_record_set" "platform_private_googleapis_wildcard" {
  project      = var.project_id
  managed_zone = google_dns_managed_zone.platform_private_googleapis.name
  name         = "*.googleapis.com."
  type         = "CNAME"
  ttl          = 300
  rrdatas      = ["private.googleapis.com."]
}
