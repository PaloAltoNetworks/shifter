# The one deployment-owned VIP; participants receive only its admitted :443 capability.
resource "google_compute_address" "model_broker" {
  count        = var.model_broker.enabled ? 1 : 0
  project      = var.project_id
  name         = "${local.name_prefix}-model-broker"
  region       = var.region
  subnetwork   = module.portal_vpc.gke_subnetwork_id
  address_type = "INTERNAL"
  purpose      = "SHARED_LOADBALANCER_VIP"
  address      = var.model_broker.vip
}

resource "google_dns_managed_zone" "model_broker" {
  count      = var.model_broker.enabled ? 1 : 0
  project    = var.project_id
  name       = "${local.name_prefix}-model-broker"
  dns_name   = "${var.model_broker.hostname}."
  visibility = "private"
  private_visibility_config {
    networks { network_url = module.range_vpc.range_network_id }
    networks { network_url = module.portal_vpc.platform_network_id }
  }
}

resource "google_dns_record_set" "model_broker" {
  count        = var.model_broker.enabled ? 1 : 0
  project      = var.project_id
  managed_zone = google_dns_managed_zone.model_broker[0].name
  name         = google_dns_managed_zone.model_broker[0].dns_name
  type         = "A"
  ttl          = 60
  rrdatas      = [google_compute_address.model_broker[0].address]
}

output "model_broker" {
  description = "Canonical broker-only transport projection consumed by Helm/runtime rendering."
  value = merge(var.model_broker, module.portal_iam.model_broker_identity, {
    vip    = try(google_compute_address.model_broker[0].address, "")
    region = var.region
  })
}

resource "terraform_data" "model_broker_network_boundary" {
  count = var.model_broker.enabled ? 1 : 0
  lifecycle {
    precondition {
      condition = alltrue([for cidr in var.model_broker.admitted_subnets : try(
        cidrhost(cidr, 0) == split("/", cidr)[0]
        && tonumber(split("/", cidr)[1]) >= tonumber(split("/", var.range_network_cidr)[1])
        && cidrhost("${split("/", cidr)[0]}/${split("/", var.range_network_cidr)[1]}", 0) == cidrhost(var.range_network_cidr, 0)
      && cidrhost(cidr, 0) != cidrhost("${var.model_broker.vip}/${split("/", cidr)[1]}", 0), false)])
      error_message = "Broker ingress must name canonical subnets inside the deployment range network, disjoint from its VIP."
    }
    precondition {
      condition     = try(cidrhost("${var.model_broker.vip}/${split("/", var.gke_subnet_cidr)[1]}", 0) == cidrhost(var.gke_subnet_cidr, 0), false)
      error_message = "Broker VIP must belong to the platform GKE subnet."
    }
  }
}
