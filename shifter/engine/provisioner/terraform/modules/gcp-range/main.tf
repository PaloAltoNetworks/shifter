locals {
  zone_parts = split("-", var.availability_zone)
  region = var.region != "" ? var.region : (
    length(local.zone_parts) > 2
    ? join("-", slice(local.zone_parts, 0, length(local.zone_parts) - 1))
    : ""
  )

  common_labels = {
    environment = substr(replace(lower(var.environment), "/[^a-z0-9_-]/", "_"), 0, 63)
    managed_by  = "terraform"
    project     = "shifter"
    range_id    = tostring(var.range_id)
    user_id     = tostring(var.user_id)
  }

  common_metadata = {
    "shifter-environment"  = var.environment
    "shifter-range-id"     = tostring(var.range_id)
    "shifter-request-uuid" = var.request_uuid
    "shifter-system"       = "shifter"
    "shifter-user-id"      = tostring(var.user_id)
  }

  subnet_map = { for s in var.subnets : s.name => s }

  subnet_target_tags = {
    for name, subnet in local.subnet_map :
    name => substr(
      trim(
        replace(
          lower("shifter-${var.range_id}-${name}-${substr(subnet.uuid, 0, 8)}"),
          "/[^a-z0-9-]/",
          "-"
        ),
        "-"
      ),
      0,
      63,
    )
  }

  all_instances = flatten([
    for subnet in var.subnets : [
      for inst in subnet.instances : {
        key           = "${subnet.name}-${inst.role}-${inst.uuid}"
        subnet_name   = subnet.name
        subnet_uuid   = subnet.uuid
        subnet_cidr   = subnet.cidr
        instance_uuid = inst.uuid
        display_name  = inst.name
        hostname      = inst.name != "" ? inst.name : "shifter-${inst.role}-${var.range_id}"
        role          = inst.role
        os_type       = inst.os_type
        instance_type = inst.instance_type
        agent_url     = inst.agent_presigned_url
        join_domain   = inst.join_domain
        image_id = inst.ami_id != "" ? inst.ami_id : lookup(
          {
            kali    = var.kali_ami_id
            ubuntu  = var.victim_ami_id
            windows = inst.role == "dc" ? var.dc_ami_id : var.windows_ami_id
          },
          inst.os_type,
          var.victim_ami_id,
        )
        is_windows = inst.role == "dc" || inst.os_type == "windows"
        ssh_user   = inst.role == "attacker" || inst.os_type == "kali" ? "kali" : "ubuntu"
        resource_name = substr(
          trim(
            replace(
              lower("shifter-${var.range_id}-${subnet.name}-${inst.role}-${substr(inst.uuid, 0, 8)}"),
              "/[^a-z0-9-]/",
              "-"
            ),
            "-"
          ),
          0,
          63,
        )
        os_label   = substr(replace(lower(inst.os_type), "/[^a-z0-9_-]/", "_"), 0, 63)
        role_label = substr(replace(lower(inst.role), "/[^a-z0-9_-]/", "_"), 0, 63)
      }
    ]
  ])

  instance_map = { for inst in local.all_instances : inst.key => inst }

  connected_ingress_rules = {
    for pair in flatten([
      for subnet in var.subnets : [
        for connected_name in subnet.connected_to : {
          key           = "${connected_name}-from-${subnet.name}"
          target_subnet = connected_name
          source_cidr   = subnet.cidr
          source_name   = subnet.name
        } if contains(keys(local.subnet_map), connected_name)
      ]
    ]) : pair.key => pair
  }

  portal_source_ranges = length(var.portal_network_cidrs) > 0 ? var.portal_network_cidrs : (
    var.portal_vpc_cidr != "" ? [var.portal_vpc_cidr] : []
  )

  dc_instances = [for inst in local.all_instances : inst if inst.role == "dc"]
}

#------------------------------------------------------------------------------
# Subnetworks
#------------------------------------------------------------------------------
resource "google_compute_subnetwork" "range" {
  for_each = local.subnet_map

  name                     = substr(trim(replace(lower("shifter-${var.range_id}-${each.key}-${substr(each.value.uuid, 0, 8)}"), "/[^a-z0-9-]/", "-"), "-"), 0, 63)
  region                   = local.region
  network                  = var.vpc_id
  ip_cidr_range            = each.value.cidr
  private_ip_google_access = true

  log_config {
    aggregation_interval = "INTERVAL_10_MIN"
    flow_sampling        = 0.1
    metadata             = "INCLUDE_ALL_METADATA"
  }
}

#------------------------------------------------------------------------------
# Firewall rules
#------------------------------------------------------------------------------
resource "google_compute_firewall" "subnet_self" {
  for_each = local.subnet_map

  name          = substr(trim(replace(lower("shifter-${var.range_id}-${each.key}-intra"), "/[^a-z0-9-]/", "-"), "-"), 0, 63)
  network       = var.vpc_id
  direction     = "INGRESS"
  source_ranges = [each.value.cidr]
  target_tags   = [local.subnet_target_tags[each.key]]

  allow {
    protocol = "all"
  }
}

resource "google_compute_firewall" "connected_subnet" {
  for_each = local.connected_ingress_rules

  name          = substr(trim(replace(lower("shifter-${var.range_id}-${each.value.target_subnet}-from-${each.value.source_name}"), "/[^a-z0-9-]/", "-"), "-"), 0, 63)
  network       = var.vpc_id
  direction     = "INGRESS"
  source_ranges = [each.value.source_cidr]
  target_tags   = [local.subnet_target_tags[each.value.target_subnet]]

  allow {
    protocol = "all"
  }
}

resource "google_compute_firewall" "portal_ssh" {
  for_each = length(local.portal_source_ranges) > 0 ? local.subnet_map : {}

  name          = substr(trim(replace(lower("shifter-${var.range_id}-${each.key}-ssh"), "/[^a-z0-9-]/", "-"), "-"), 0, 63)
  network       = var.vpc_id
  direction     = "INGRESS"
  source_ranges = local.portal_source_ranges
  target_tags   = [local.subnet_target_tags[each.key]]

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }
}

resource "google_compute_firewall" "portal_rdp" {
  for_each = length(local.portal_source_ranges) > 0 ? local.subnet_map : {}

  name          = substr(trim(replace(lower("shifter-${var.range_id}-${each.key}-rdp"), "/[^a-z0-9-]/", "-"), "-"), 0, 63)
  network       = var.vpc_id
  direction     = "INGRESS"
  source_ranges = local.portal_source_ranges
  target_tags   = [local.subnet_target_tags[each.key]]

  allow {
    protocol = "tcp"
    ports    = ["3389"]
  }
}

#------------------------------------------------------------------------------
# SSH keys and DC bootstrap secret
#------------------------------------------------------------------------------
resource "tls_private_key" "instance" {
  for_each = local.instance_map

  algorithm = "RSA"
  rsa_bits  = 4096
}

resource "google_secret_manager_secret" "ssh_key" {
  for_each = local.instance_map

  secret_id = substr(trim(replace(lower("shifter-${var.environment}-range-${var.range_id}-${substr(each.value.instance_uuid, 0, 8)}-ssh-key"), "/[^a-z0-9-_]/", "-"), "-"), 0, 255)
  labels = merge(local.common_labels, {
    role = each.value.role_label
  })

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "ssh_key" {
  for_each = local.instance_map

  secret      = google_secret_manager_secret.ssh_key[each.key].id
  secret_data = tls_private_key.instance[each.key].private_key_pem
}

resource "google_secret_manager_secret" "dc_config" {
  count = length(local.dc_instances) > 0 ? 1 : 0

  secret_id = substr(trim(replace(lower("shifter-${var.environment}-range-${var.range_id}-dc-config"), "/[^a-z0-9-_]/", "-"), "-"), 0, 255)
  labels    = local.common_labels

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "dc_config" {
  count = length(local.dc_instances) > 0 ? 1 : 0

  secret      = google_secret_manager_secret.dc_config[0].id
  secret_data = "{}"
}

#------------------------------------------------------------------------------
# Instances
#------------------------------------------------------------------------------
resource "google_compute_instance" "range" {
  for_each = local.instance_map

  name         = each.value.resource_name
  machine_type = each.value.instance_type
  zone         = var.availability_zone
  tags         = [local.subnet_target_tags[each.value.subnet_name]]

  labels = merge(local.common_labels, {
    os         = each.value.os_label
    role       = each.value.role_label
    subnet     = substr(replace(lower(each.value.subnet_name), "/[^a-z0-9_-]/", "_"), 0, 63)
    instanceid = substr(replace(lower(substr(each.value.instance_uuid, 0, 8)), "/[^a-z0-9_-]/", "_"), 0, 63)
  })

  boot_disk {
    auto_delete = true

    initialize_params {
      image = each.value.image_id
      size  = var.boot_disk_size_gb
      type  = var.boot_disk_type
    }
  }

  network_interface {
    subnetwork = google_compute_subnetwork.range[each.value.subnet_name].self_link
  }

  metadata = merge(
    local.common_metadata,
    {
      "shifter-instance-uuid" = each.value.instance_uuid
      "shifter-role"          = each.value.role
      "shifter-subnet-name"   = each.value.subnet_name
      "serial-port-enable"    = "TRUE"
    },
    each.value.is_windows ? {} : {
      "ssh-keys" = "${each.value.ssh_user}:${tls_private_key.instance[each.key].public_key_openssh}"
    },
    each.value.is_windows ? {
      "windows-startup-script-ps1" = each.value.role == "dc" ? templatefile("${path.module}/templates/dc_windows.ps1.tpl", {
        admin_password = var.windows_admin_password
        hostname       = each.value.hostname
        public_key     = tls_private_key.instance[each.key].public_key_openssh
        }) : templatefile("${path.module}/templates/victim_windows.ps1.tpl", {
        admin_password = var.windows_admin_password
        hostname       = each.value.hostname
        public_key     = tls_private_key.instance[each.key].public_key_openssh
      })
      } : {
      "startup-script" = each.value.role == "attacker" ? templatefile("${path.module}/templates/kali.sh.tpl", {
        hostname   = each.value.hostname
        public_key = tls_private_key.instance[each.key].public_key_openssh
        ssh_user   = each.value.ssh_user
        }) : templatefile("${path.module}/templates/victim_linux.sh.tpl", {
        hostname   = each.value.hostname
        public_key = tls_private_key.instance[each.key].public_key_openssh
        ssh_user   = each.value.ssh_user
      })
    },
  )

  dynamic "service_account" {
    for_each = var.service_account_email != "" ? [var.service_account_email] : []
    content {
      email  = service_account.value
      scopes = var.service_account_scopes
    }
  }

  depends_on = [
    google_secret_manager_secret_version.ssh_key,
    google_compute_firewall.subnet_self,
    google_compute_subnetwork.range,
  ]
}
