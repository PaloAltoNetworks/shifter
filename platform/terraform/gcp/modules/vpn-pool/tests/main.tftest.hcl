# Shared OpenVPN pool network and identity envelope contract test (#2480).
#
# Proves the pool's exposure is exactly the reviewed envelope: one public
# listener (UDP 1194), health probes only from Google's probe ranges, egress only
# to range targets on 22/3389 and to the portal and Google API VIP on 443, and a
# deny-all below every allow. The servers have no public address, run Shielded
# VM, are replaced without losing capacity, and their identity reads only its own
# server secret and the release record, never the CA.
#
# Credential-free: mock_provider synthesizes the google provider; `command = plan`
# is sufficient because every asserted value is configuration-known.
# Run with:
#   terraform -chdir=platform/terraform/gcp/modules/vpn-pool test

mock_provider "google" {}

variables {
  project_id                        = "shifter-test"
  region                            = "us-central1"
  zones                             = ["us-central1-a", "us-central1-b", "us-central1-c"]
  name_prefix                       = "shifter-test"
  network_id                        = "projects/shifter-test/global/networks/shifter-test-range"
  network_name                      = "shifter-test-range"
  subnet_cidr                       = "10.49.0.0/24"
  range_network_cidr                = "10.50.0.0/16"
  public_hostname                   = "portal.example.com"
  portal_ingress_ip                 = "203.0.113.10"
  artifact_registry_location        = "us-central1"
  artifact_repository               = "shifter-test-openvpn"
  deploy_service_account_email      = "deploy@shifter-test.iam.gserviceaccount.com"
  provisioner_service_account_email = "provisioner@shifter-test.iam.gserviceaccount.com"
  min_vms                           = 2
  max_vms                           = 4
}

run "public_exposure_is_one_udp_listener_and_probe_ranges" {
  command = plan

  assert {
    condition     = google_compute_forwarding_rule.pool.ip_protocol == "UDP" && google_compute_forwarding_rule.pool.ports == toset(["1194"])
    error_message = "The pool load balancer must expose only UDP 1194."
  }

  assert {
    condition = (
      length(google_compute_firewall.pool_vpn_ingress.allow) == 1
      && one(google_compute_firewall.pool_vpn_ingress.allow).protocol == "udp"
      && one(google_compute_firewall.pool_vpn_ingress.allow).ports == tolist(["1194"])
    )
    error_message = "The only world-reachable pool ingress must be UDP 1194."
  }

  assert {
    condition = (
      toset(google_compute_firewall.pool_health_ingress.source_ranges) == toset(["35.191.0.0/16", "130.211.0.0/22", "209.85.204.0/22"])
      && one(google_compute_firewall.pool_health_ingress.allow).ports == tolist(["8080"])
    )
    error_message = "Health ingress must come only from Google's probe ranges to the health port."
  }

  assert {
    condition     = length(google_compute_region_health_check.pool.tcp_health_check) == 1 && length(google_compute_region_health_check.pool.http_health_check) == 0
    error_message = "Health is a TCP handshake on the health port; the server exposes no HTTP endpoint."
  }

  assert {
    condition     = alltrue([for nic in google_compute_region_instance_template.pool.network_interface : length(nic.access_config) == 0])
    error_message = "Pool servers must not have public addresses."
  }
}

run "every_allow_sits_above_a_deny_all" {
  command = plan

  assert {
    condition = alltrue([
      for rule in [
        google_compute_firewall.pool_vpn_ingress,
        google_compute_firewall.pool_health_ingress,
        google_compute_firewall.pool_range_egress,
        google_compute_firewall.pool_control_egress,
      ] : rule.priority < google_compute_firewall.pool_ingress_deny.priority && rule.priority < 1000
    ])
    error_message = "Pool allows must outrank the pool denies, and both must outrank the range-wide rules at 1000."
  }

  assert {
    condition = (
      google_compute_firewall.pool_ingress_deny.priority < 1000
      && google_compute_firewall.pool_egress_deny.priority < 1000
      && one(google_compute_firewall.pool_ingress_deny.deny).protocol == "all"
      && one(google_compute_firewall.pool_egress_deny.deny).protocol == "all"
      && google_compute_firewall.pool_egress_deny.destination_ranges == toset(["0.0.0.0/0"])
    )
    error_message = "The pool must deny all other ingress and egress above the range-wide rules."
  }

  assert {
    condition = (
      google_compute_firewall.pool_range_egress.destination_ranges == toset(["10.50.0.0/16"])
      && toset(one(google_compute_firewall.pool_range_egress.allow).ports) == toset(["22", "3389"])
      && one(google_compute_firewall.pool_range_egress.allow).protocol == "tcp"
    )
    error_message = "Pool egress into the range must be TCP 22/3389 only."
  }

  assert {
    condition = (
      google_compute_firewall.pool_control_egress.destination_ranges == toset(["203.0.113.10/32", "199.36.153.8/30"])
      && one(google_compute_firewall.pool_control_egress.allow).ports == tolist(["443"])
    )
    error_message = "Pool control egress must reach only the portal ingress and the Google API VIP on 443."
  }
}

run "servers_are_hardened_and_replaced_without_losing_capacity" {
  command = plan

  assert {
    condition = (
      one(google_compute_region_instance_template.pool.shielded_instance_config).enable_secure_boot
      && one(google_compute_region_instance_template.pool.shielded_instance_config).enable_integrity_monitoring
    )
    error_message = "Pool servers must run Shielded VM with secure boot and integrity monitoring."
  }

  assert {
    condition = (
      google_compute_region_instance_template.pool.metadata["block-project-ssh-keys"] == "true"
      && google_compute_region_instance_template.pool.metadata["enable-oslogin"] == "TRUE"
    )
    error_message = "Pool servers must block project SSH keys and use OS Login."
  }

  assert {
    condition     = one(google_compute_region_instance_group_manager.pool.update_policy).max_unavailable_fixed == 0
    error_message = "Server replacement must surge in new servers before removing old ones."
  }
}

run "the_pool_identity_never_reads_the_ca" {
  command = plan

  assert {
    condition     = toset(keys(google_secret_manager_secret_iam_member.pool_reads)) == toset(["server", "release"])
    error_message = "The pool identity may read only its server secret and the release record."
  }

  assert {
    condition     = google_secret_manager_secret_iam_member.provisioner_reads_issuer.member == "serviceAccount:provisioner@shifter-test.iam.gserviceaccount.com"
    error_message = "Only the provisioner reads the issuer (CA) secret."
  }

  assert {
    condition = (
      google_service_account_iam_member.deploy_act_as_pool.role == "roles/iam.serviceAccountUser"
      && google_service_account_iam_member.deploy_act_as_pool.member == "serviceAccount:deploy@shifter-test.iam.gserviceaccount.com"
    )
    error_message = "The deploy identity may act as the pool identity only through the SA-scoped binding."
  }
}

# #2535: the pool subnet and its NAT sit in the range VPC, so they follow the same
# range audit telemetry policy as the provisioner-created range subnets and NATs.
run "pool_subnet_and_nat_log_by_default" {
  command = plan

  assert {
    condition = (
      google_compute_subnetwork.pool.log_config[0].aggregation_interval == "INTERVAL_5_SEC"
      && google_compute_subnetwork.pool.log_config[0].flow_sampling == 0.5
      && google_compute_subnetwork.pool.log_config[0].metadata == "INCLUDE_ALL_METADATA"
    )
    error_message = "The pool subnet must carry the default range flow-log settings (#2535)."
  }

  assert {
    condition     = google_compute_router_nat.pool.log_config[0].enable == true && google_compute_router_nat.pool.log_config[0].filter == "ALL"
    error_message = "The pool NAT must log translations and errors by default (#2535)."
  }
}

run "pool_follows_the_operator_telemetry_policy" {
  command = plan

  variables {
    vpc_flow_logs = { enabled = true, aggregation_interval = "INTERVAL_1_MIN", flow_sampling = 0.1, metadata = "EXCLUDE_ALL_METADATA" }
    nat_logs      = { enabled = false, filter = "ALL" }
  }

  assert {
    condition     = google_compute_subnetwork.pool.log_config[0].aggregation_interval == "INTERVAL_1_MIN" && google_compute_subnetwork.pool.log_config[0].flow_sampling == 0.1
    error_message = "The pool subnet must use the operator flow-log settings (#2535)."
  }

  assert {
    condition     = google_compute_router_nat.pool.log_config[0].enable == false
    error_message = "An explicit nat_logs.enabled = false must disable pool NAT logging (#2535)."
  }
}

run "pool_flow_logs_disabled_removes_the_subnet_log_config" {
  command = plan

  variables {
    vpc_flow_logs = { enabled = false }
  }

  assert {
    condition     = length(google_compute_subnetwork.pool.log_config) == 0
    error_message = "Disabled flow logs must render no subnet log_config block (#2535)."
  }
}

run "pool_telemetry_resource_names_are_published_for_the_readback" {
  command = plan

  assert {
    condition     = output.subnetwork_name == "shifter-test-vpn" && output.nat_router_name == "shifter-test-vpn-nat"
    error_message = "The pool must publish its Terraform-owned subnet and NAT router names (#2535)."
  }
}
