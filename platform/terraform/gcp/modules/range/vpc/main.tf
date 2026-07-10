resource "google_compute_network" "range" {
  name                    = "${var.name_prefix}-range"
  project                 = var.project_id
  auto_create_subnetworks = false
}

# Private Google Access egress path for range guests. The Polaris range needs to
# reach Google APIs from VMs with no external IP and (per the per-range
# firewall) no general internet egress: Vertex AI for the a14-kali agent, Cloud
# Storage for the smoketest tarball, and Secret Manager for the per-range Vertex
# key. This routes the private.googleapis.com VIP (199.36.153.8/30) over
# Google's internal fabric and resolves *.googleapis.com to it, so the only
# egress hole the range-cell provisioner has to open is that /30 (it emits the
# matching egress-allow when private_google_access is set). See
# GCERangeCellConfig.private_google_access and _firewall_plan.
resource "google_compute_route" "range_private_googleapis" {
  name             = "${var.name_prefix}-range-private-googleapis"
  project          = var.project_id
  network          = google_compute_network.range.name
  description      = "Private Google Access: route the private.googleapis.com VIP over Google's internal fabric for range guests."
  dest_range       = "199.36.153.8/30"
  next_hop_gateway = "default-internet-gateway"
  priority         = 1000
}

resource "google_dns_managed_zone" "range_private_googleapis" {
  name        = "${var.name_prefix}-range-googleapis"
  project     = var.project_id
  dns_name    = "googleapis.com."
  description = "Private Google Access: resolve *.googleapis.com to the private.googleapis.com VIP for range guests."

  visibility = "private"

  private_visibility_config {
    networks {
      network_url = google_compute_network.range.id
    }
  }
}

resource "google_dns_record_set" "range_private_googleapis_a" {
  project      = var.project_id
  managed_zone = google_dns_managed_zone.range_private_googleapis.name
  name         = "private.googleapis.com."
  type         = "A"
  ttl          = 300
  rrdatas      = ["199.36.153.8", "199.36.153.9", "199.36.153.10", "199.36.153.11"]
}

resource "google_dns_record_set" "range_private_googleapis_wildcard" {
  project      = var.project_id
  managed_zone = google_dns_managed_zone.range_private_googleapis.name
  name         = "*.googleapis.com."
  type         = "CNAME"
  ttl          = 300
  rrdatas      = ["private.googleapis.com."]
}

resource "google_compute_router" "range_nat" {
  name    = "${var.name_prefix}-range-nat"
  project = var.project_id
  region  = var.region
  network = google_compute_network.range.id
}

resource "google_compute_address" "range_nat" {
  name         = "${var.name_prefix}-range-nat-egress"
  project      = var.project_id
  region       = var.region
  address_type = "EXTERNAL"
}

resource "google_compute_router_nat" "range_nat" {
  name                               = "${var.name_prefix}-range-nat"
  project                            = var.project_id
  region                             = var.region
  router                             = google_compute_router.range_nat.name
  nat_ip_allocate_option             = "MANUAL_ONLY"
  nat_ips                            = [google_compute_address.range_nat.self_link]
  source_subnetwork_ip_ranges_to_nat = "ALL_SUBNETWORKS_ALL_IP_RANGES"
}

resource "google_compute_firewall" "range_deny_ingress_all" {
  name        = "${var.name_prefix}-range-deny-ingress-all"
  project     = var.project_id
  network     = google_compute_network.range.name
  description = "ADR-008-R4: range VPC ingress is denied by default; explicit allow rules ride higher precedence."
  direction   = "INGRESS"
  priority    = 65000

  source_ranges = ["0.0.0.0/0"]

  deny {
    protocol = "all"
  }
}

resource "google_compute_firewall" "range_allow_platform_provisioner" {
  name        = "${var.name_prefix}-range-allow-platform-provisioner"
  project     = var.project_id
  network     = google_compute_network.range.name
  description = "ADR-008-R4: provisioner-pod traffic (dedicated GKE pod range) into range VMs on documented ports only."
  direction   = "INGRESS"
  priority    = 1000

  source_ranges = [var.gke_provisioner_pods_cidr]

  allow {
    protocol = "tcp"
    ports    = [for p in var.range_provisioner_ports : tostring(p)]
  }
}

resource "google_compute_firewall" "range_allow_operator_admin_ssh" {
  count = length(var.operator_admin_cidrs) > 0 ? 1 : 0

  name        = "${var.name_prefix}-range-allow-operator-admin-ssh"
  project     = var.project_id
  network     = google_compute_network.range.name
  description = "ADR-008-R4: break-glass direct SSH into range VMs from the operator-admin CIDR allowlist (not IAP)."
  direction   = "INGRESS"
  priority    = 800

  source_ranges = var.operator_admin_cidrs

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }
}

resource "terraform_data" "range_egress_invariant" {
  lifecycle {
    precondition {
      condition = (
        (var.range_egress_mode == "status-quo" && length(var.range_egress_allowed_cidrs) == 0)
        || (var.range_egress_mode == "deny-all" && length(var.range_egress_allowed_cidrs) == 0)
        || (var.range_egress_mode == "allowlist" && length(var.range_egress_allowed_cidrs) > 0)
      )
      error_message = "PLAT-220: range_egress_mode='allowlist' requires a non-empty range_egress_allowed_cidrs; range_egress_mode='deny-all' or 'status-quo' must carry an empty list. The public RangeEgressPolicy contract (shifter/installation/range_egress.py) enforces this; this precondition mirrors it for direct Terraform use."
    }
  }
}

resource "google_compute_firewall" "range_egress_deny_all" {
  count = var.range_egress_mode == "status-quo" ? 0 : 1

  name        = "${var.name_prefix}-range-egress-deny-all"
  project     = var.project_id
  network     = google_compute_network.range.name
  description = "PLAT-220: range egress is policy-driven. Low-precedence deny enforces fail-closed when the operator selects deny-all or allowlist; the allowlist rule rides higher precedence."
  direction   = "EGRESS"
  priority    = 65534

  destination_ranges = ["0.0.0.0/0"]

  deny {
    protocol = "all"
  }
}

resource "google_compute_firewall" "range_egress_allow_allowlist" {
  count = var.range_egress_mode == "allowlist" && length(var.range_egress_allowed_cidrs) > 0 ? 1 : 0

  name        = "${var.name_prefix}-range-egress-allow-allowlist"
  project     = var.project_id
  network     = google_compute_network.range.name
  description = "PLAT-220: range egress allowlist (HTTPS to operator-declared CIDRs). Higher precedence than the deny-all base so the named destinations actually reach the internet."
  direction   = "EGRESS"
  priority    = 1000

  destination_ranges = var.range_egress_allowed_cidrs

  allow {
    protocol = "tcp"
    ports    = ["443"]
  }
}
