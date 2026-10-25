# Shared participant OpenVPN server pool (#2480, ADR-039-R10).
#
# A regional managed instance group of Container-Optimized OS VMs in their own
# subnet of the range VPC, behind an external passthrough UDP load balancer on
# a reserved address. Each VM runs one OpenVPN process with the controller that
# asks the portal to authorize every connection. The VMs have no public
# addresses; a NAT scoped to the pool subnet carries only the portal call.
#
# Private keys never enter Terraform state: this module creates the empty
# secrets and their IAM, and the deploy workflow writes the PKI (scripts/gcp/
# ensure_vpn_pki.py) and the release record (image digest) directly.

data "google_compute_zones" "available" {
  project = var.project_id
  region  = var.region
  status  = "UP"
}

locals {
  zones            = length(var.zones) > 0 ? var.zones : slice(sort(data.google_compute_zones.available.names), 0, min(3, length(data.google_compute_zones.available.names)))
  name             = "${var.name_prefix}-vpn"
  tag              = "${var.name_prefix}-vpn-pool"
  image_root       = "${var.artifact_registry_location}-docker.pkg.dev/${var.project_id}/${var.artifact_repository}/openvpn"
  registry         = "${var.artifact_registry_location}-docker.pkg.dev"
  portal_url       = "https://${var.public_hostname}"
  control_audience = "https://${var.public_hostname}/vpn-control"
  # Autohealing probes (35.191.0.0/16, 130.211.0.0/22) and regional external
  # passthrough load-balancer probes (35.191.0.0/16, 209.85.204.0/22).
  health_check_cidrs = ["35.191.0.0/16", "130.211.0.0/22", "209.85.204.0/22"]
  private_api_vip    = "199.36.153.8/30"
}

resource "google_compute_subnetwork" "pool" {
  name                     = local.name
  project                  = var.project_id
  region                   = var.region
  network                  = var.network_id
  ip_cidr_range            = var.subnet_cidr
  private_ip_google_access = true

  # #2535: the pool subnet sits in the range VPC and follows the range flow-log policy.
  dynamic "log_config" {
    for_each = var.vpc_flow_logs.enabled ? [var.vpc_flow_logs] : []
    content {
      aggregation_interval = log_config.value.aggregation_interval
      flow_sampling        = log_config.value.flow_sampling
      metadata             = log_config.value.metadata
    }
  }
}

resource "google_compute_router" "pool" {
  name    = "${local.name}-nat"
  project = var.project_id
  region  = var.region
  network = var.network_id
}

resource "google_compute_address" "pool_nat" {
  name         = "${local.name}-nat-egress"
  project      = var.project_id
  region       = var.region
  address_type = "EXTERNAL"
}

# Only the pool subnet is translated; range subnets keep their own egress posture.
resource "google_compute_router_nat" "pool" {
  name                               = "${local.name}-nat"
  project                            = var.project_id
  region                             = var.region
  router                             = google_compute_router.pool.name
  nat_ip_allocate_option             = "MANUAL_ONLY"
  nat_ips                            = [google_compute_address.pool_nat.self_link]
  source_subnetwork_ip_ranges_to_nat = "LIST_OF_SUBNETWORKS"

  subnetwork {
    name                    = google_compute_subnetwork.pool.id
    source_ip_ranges_to_nat = ["ALL_IP_RANGES"]
  }

  log_config {
    enable = var.nat_logs.enabled
    filter = var.nat_logs.filter
  }
}

# Artifact Registry over Private Google Access, like *.googleapis.com already is.
resource "google_dns_managed_zone" "pkg_dev" {
  name        = "${local.name}-pkg-dev"
  project     = var.project_id
  dns_name    = "pkg.dev."
  description = "Private Google Access: resolve *.pkg.dev to the private.googleapis.com VIP for the OpenVPN pool."
  visibility  = "private"

  private_visibility_config {
    networks {
      network_url = var.network_id
    }
  }
}

resource "google_dns_record_set" "pkg_dev_wildcard" {
  project      = var.project_id
  managed_zone = google_dns_managed_zone.pkg_dev.name
  name         = "*.pkg.dev."
  type         = "CNAME"
  ttl          = 300
  rrdatas      = ["private.googleapis.com."]
}

resource "google_service_account" "pool" {
  project      = var.project_id
  account_id   = local.name
  display_name = "Shifter shared OpenVPN pool servers"
}

# The deploy identity attaches the pool SA to the servers it creates. Scoped to
# this one SA (not a project-wide serviceAccountUser), like the GKE node SA.
resource "google_service_account_iam_member" "deploy_act_as_pool" {
  service_account_id = google_service_account.pool.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${var.deploy_service_account_email}"
}

resource "google_secret_manager_secret" "pool" {
  for_each = toset(["issuer", "server", "release"])

  project   = var.project_id
  secret_id = "${local.name}-${each.key}"
  labels    = var.common_labels

  replication {
    auto {}
  }
}

# The pool reads its server identity and the release record; never the issuer.
resource "google_secret_manager_secret_iam_member" "pool_reads" {
  for_each = toset(["server", "release"])

  project   = var.project_id
  secret_id = google_secret_manager_secret.pool[each.key].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.pool.email}"
}

# Only the provisioner signs participant certificates.
resource "google_secret_manager_secret_iam_member" "provisioner_reads_issuer" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.pool["issuer"].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${var.provisioner_service_account_email}"
}

resource "google_artifact_registry_repository_iam_member" "pool_pulls" {
  project    = var.project_id
  location   = var.artifact_registry_location
  repository = var.artifact_repository
  role       = "roles/artifactregistry.reader"
  member     = "serviceAccount:${google_service_account.pool.email}"
}

resource "google_project_iam_member" "pool_telemetry" {
  for_each = toset(["roles/logging.logWriter", "roles/monitoring.metricWriter"])

  project = var.project_id
  role    = each.key
  member  = "serviceAccount:${google_service_account.pool.email}"
}

resource "google_compute_address" "endpoint" {
  name         = "${local.name}-endpoint"
  project      = var.project_id
  region       = var.region
  address_type = "EXTERNAL"
  network_tier = "PREMIUM"
}

resource "google_compute_region_health_check" "pool" {
  name                = local.name
  project             = var.project_id
  region              = var.region
  check_interval_sec  = 5
  timeout_sec         = 5
  healthy_threshold   = 2
  unhealthy_threshold = 3

  # The server opens the health port only once it is serving; a completed TCP
  # handshake is the health signal.
  tcp_health_check {
    port = var.health_port
  }

  log_config {
    enable = true
  }
}

resource "google_compute_region_instance_template" "pool" {
  name_prefix  = "${local.name}-"
  project      = var.project_id
  region       = var.region
  machine_type = var.machine_type
  tags         = [local.tag]
  labels       = merge(var.common_labels, { role = "vpn-pool" })

  disk {
    boot         = true
    auto_delete  = true
    source_image = "projects/cos-cloud/global/images/family/cos-stable"
    disk_size_gb = 20
    disk_type    = "pd-balanced"
  }

  network_interface {
    subnetwork = google_compute_subnetwork.pool.id
  }

  service_account {
    email  = google_service_account.pool.email
    scopes = ["cloud-platform"]
  }

  shielded_instance_config {
    enable_secure_boot          = true
    enable_vtpm                 = true
    enable_integrity_monitoring = true
  }

  metadata = {
    block-project-ssh-keys = "true"
    enable-oslogin         = "TRUE"
    google-logging-enabled = "true"
    cos-update-strategy    = "update_disabled"
    user-data = templatefile("${path.module}/cloud-init.yaml.tftpl", {
      release_secret         = google_secret_manager_secret.pool["release"].id
      server_secret          = google_secret_manager_secret.pool["server"].id
      image_repository       = local.image_root
      image_repository_regex = replace(local.image_root, ".", "\\.")
      registry               = local.registry
      endpoint               = google_compute_address.endpoint.address
      portal_url             = local.portal_url
      control_audience       = local.control_audience
      max_clients            = var.max_clients_per_vm
      tunnel_network         = var.tunnel_network
      health_port            = var.health_port
    })
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "google_compute_region_instance_group_manager" "pool" {
  depends_on = [google_service_account_iam_member.deploy_act_as_pool]

  name                      = local.name
  project                   = var.project_id
  region                    = var.region
  base_instance_name        = local.name
  distribution_policy_zones = local.zones

  version {
    instance_template = google_compute_region_instance_template.pool.self_link
  }

  named_port {
    name = "health"
    port = var.health_port
  }

  auto_healing_policies {
    health_check      = google_compute_region_health_check.pool.id
    initial_delay_sec = 300
  }

  # Replacements surge in before old servers leave, so capacity never dips.
  update_policy {
    type                         = "PROACTIVE"
    minimal_action               = "REPLACE"
    replacement_method           = "SUBSTITUTE"
    max_surge_fixed              = length(local.zones)
    max_unavailable_fixed        = 0
    instance_redistribution_type = "PROACTIVE"
  }
}

resource "google_compute_region_autoscaler" "pool" {
  name    = local.name
  project = var.project_id
  region  = var.region
  target  = google_compute_region_instance_group_manager.pool.id

  autoscaling_policy {
    min_replicas    = var.min_vms
    max_replicas    = var.max_vms
    cooldown_period = 180

    # One OpenVPN process uses one core: a busy server is half of a 2-vCPU VM.
    cpu_utilization {
      target = var.cpu_target_pct / 100
    }

    # Scale in slowly; removing a server disconnects its participants once.
    scale_in_control {
      max_scaled_in_replicas {
        fixed = 1
      }
      time_window_sec = 900
    }
  }
}

resource "google_compute_region_backend_service" "pool" {
  name                            = local.name
  project                         = var.project_id
  region                          = var.region
  protocol                        = "UDP"
  load_balancing_scheme           = "EXTERNAL"
  session_affinity                = "CLIENT_IP"
  health_checks                   = [google_compute_region_health_check.pool.id]
  connection_draining_timeout_sec = 30

  backend {
    group          = google_compute_region_instance_group_manager.pool.instance_group
    balancing_mode = "CONNECTION"
  }

  log_config {
    enable = true
  }
}

resource "google_compute_forwarding_rule" "pool" {
  name                  = local.name
  project               = var.project_id
  region                = var.region
  ip_address            = google_compute_address.endpoint.address
  ip_protocol           = "UDP"
  ports                 = ["1194"]
  load_balancing_scheme = "EXTERNAL"
  backend_service       = google_compute_region_backend_service.pool.id
}

# Firewall envelope. Allows sit above the denies, and both above the range-wide
# rules (provisioner management ingress and allowlist egress at 1000), so the
# pool's traffic is exactly what is listed here.
resource "google_compute_firewall" "pool_vpn_ingress" {
  name          = "${local.name}-in"
  project       = var.project_id
  network       = var.network_name
  direction     = "INGRESS"
  priority      = 900
  target_tags   = [local.tag]
  source_ranges = ["0.0.0.0/0"]

  allow {
    protocol = "udp"
    ports    = ["1194"]
  }
}

resource "google_compute_firewall" "pool_health_ingress" {
  name          = "${local.name}-health"
  project       = var.project_id
  network       = var.network_name
  direction     = "INGRESS"
  priority      = 900
  target_tags   = [local.tag]
  source_ranges = local.health_check_cidrs

  allow {
    protocol = "tcp"
    ports    = [tostring(var.health_port)]
  }
}

resource "google_compute_firewall" "pool_ingress_deny" {
  name          = "${local.name}-in-deny"
  project       = var.project_id
  network       = var.network_name
  direction     = "INGRESS"
  priority      = 950
  target_tags   = [local.tag]
  source_ranges = ["0.0.0.0/0"]

  deny {
    protocol = "all"
  }
}

resource "google_compute_firewall" "pool_range_egress" {
  name               = "${local.name}-to-range"
  project            = var.project_id
  network            = var.network_name
  direction          = "EGRESS"
  priority           = 900
  target_tags        = [local.tag]
  destination_ranges = [var.range_network_cidr]

  allow {
    protocol = "tcp"
    ports    = ["22", "3389"]
  }
}

resource "google_compute_firewall" "pool_control_egress" {
  name               = "${local.name}-to-control"
  project            = var.project_id
  network            = var.network_name
  direction          = "EGRESS"
  priority           = 900
  target_tags        = [local.tag]
  destination_ranges = ["${var.portal_ingress_ip}/32", local.private_api_vip]

  allow {
    protocol = "tcp"
    ports    = ["443"]
  }
}

resource "google_compute_firewall" "pool_egress_deny" {
  name               = "${local.name}-out-deny"
  project            = var.project_id
  network            = var.network_name
  direction          = "EGRESS"
  priority           = 950
  target_tags        = [local.tag]
  destination_ranges = ["0.0.0.0/0"]

  deny {
    protocol = "all"
  }
}
