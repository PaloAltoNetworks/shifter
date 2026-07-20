# Dedicated, custom-mode VPC for the GCP-native GitHub Actions runner
# (issue #1546). The runner is development-plane infrastructure that lives in the
# dev tenant's own project so the tenant is self-contained (never borrows the AWS
# fleet), but it is network-isolated: a custom VPC with no peering to the
# platform or range networks, no external IP on the instance, private-only SSH
# reachable through IAP alone, and Cloud NAT for egress. This mirrors the AWS
# dedicated runner VPC (platform/terraform/modules/github-runner-network) and the
# GCP range VPC isolation idiom (platform/terraform/gcp/modules/range/vpc), and
# satisfies ADR-008-R2/R4 (private operator access; explicit least-privilege
# firewall; SSH never opened to the world). The check_tf_gcp_runner_network guard
# pins the custom-VPC + IAP-only-SSH invariants.

locals {
  # Google's fixed IAP TCP-forwarding relay range. Hardcoded (not a variable) so
  # SSH ingress can never be widened to a public or broad CIDR by an override;
  # this is the only source range the runner's SSH firewall admits.
  iap_tcp_source_range = "35.235.240.0/20"
}

resource "google_compute_network" "runner" {
  name                    = "${var.name_prefix}-runner"
  project                 = var.project_id
  auto_create_subnetworks = false
}

resource "google_compute_subnetwork" "runner" {
  name          = "${var.name_prefix}-runner"
  project       = var.project_id
  region        = var.region
  network       = google_compute_network.runner.id
  ip_cidr_range = var.runner_subnet_cidr

  # Reach Google APIs (logging/monitoring) from instances with no external IP.
  private_ip_google_access = true

  # Subnet flow logs for auditability (ADR-008-R4).
  log_config {
    aggregation_interval = "INTERVAL_5_SEC"
    flow_sampling        = 0.5
    metadata             = "INCLUDE_ALL_METADATA"
  }
}

# Cloud NAT for egress: the runner needs outbound internet (github.com, the
# Actions runner download, package repos) but has no external IP. A reserved
# static egress address keeps the source IP stable (a natural future input to
# GKE master-authorized networks without coupling the runner VPC to GKE).
resource "google_compute_router" "runner_nat" {
  name    = "${var.name_prefix}-runner-nat"
  project = var.project_id
  region  = var.region
  network = google_compute_network.runner.id
}

resource "google_compute_address" "runner_nat" {
  name         = "${var.name_prefix}-runner-nat-egress"
  project      = var.project_id
  region       = var.region
  address_type = "EXTERNAL"
}

resource "google_compute_router_nat" "runner_nat" {
  name                               = "${var.name_prefix}-runner-nat"
  project                            = var.project_id
  region                             = var.region
  router                             = google_compute_router.runner_nat.name
  nat_ip_allocate_option             = "MANUAL_ONLY"
  nat_ips                            = [google_compute_address.runner_nat.self_link]
  source_subnetwork_ip_ranges_to_nat = "ALL_SUBNETWORKS_ALL_IP_RANGES"
}

# Fail-closed default: deny all ingress. Explicit allow rules ride higher
# precedence. (A deny from 0.0.0.0/0 is the required baseline, not world-open
# ingress -- world-open would be an *allow* from 0.0.0.0/0.)
resource "google_compute_firewall" "runner_deny_ingress_all" {
  name        = "${var.name_prefix}-runner-deny-ingress-all"
  project     = var.project_id
  network     = google_compute_network.runner.name
  description = "ADR-008-R4: runner VPC ingress is denied by default; explicit allow rules ride higher precedence."
  direction   = "INGRESS"
  priority    = 65000

  source_ranges = ["0.0.0.0/0"]

  deny {
    protocol = "all"
  }
}

# The only ingress: SSH from Google's IAP TCP-forwarding range, targeted at the
# runner service account. Registration and any operator access ride IAP; SSH is
# never open to the world or a broad external CIDR (ADR-008-R2/R4).
resource "google_compute_firewall" "runner_iap_ssh" {
  name        = "${var.name_prefix}-runner-iap-ssh"
  project     = var.project_id
  network     = google_compute_network.runner.name
  description = "ADR-008-R2/R4: SSH into the runner only from Google's IAP relay range, targeted by service account."
  direction   = "INGRESS"
  priority    = 1000

  source_ranges           = [local.iap_tcp_source_range]
  target_service_accounts = [var.runner_service_account_email]

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }
}
