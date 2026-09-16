# Range VPC shared-NAT migration-bridge contract test (#1295).
#
# Proves the shared range Cloud NAT (primary region and additional pooled regions)
# enrolls only the explicitly listed pre-migration subnets via LIST_OF_SUBNETWORKS
# and never ALL_SUBNETWORKS -- the latter would NAT a zero-egress `none` range
# because a firewall deny does not remove NAT enrollment (ADR-026-R6). Regression
# guard for the extra-region NAT added by #2029.
#
# Credential-free: mock_provider synthesizes the google provider; `command = plan`
# is sufficient because the NAT enrollment mode is a configuration-known value.
# Run with:
#   terraform -chdir=platform/terraform/gcp/modules/range/vpc test

mock_provider "google" {}

variables {
  project_id                 = "shifter-test"
  region                     = "us-central1"
  name_prefix                = "shifter-test"
  gke_provisioner_pods_cidr  = "10.40.0.0/20"
  range_provisioner_ports    = [22]
  operator_admin_cidrs       = []
  range_egress_mode          = "status-quo"
  range_egress_allowed_cidrs = []
  shared_range_nat_subnetwork_self_links = [
    "https://www.googleapis.com/compute/v1/projects/shifter-test/regions/us-central1/subnetworks/range-a",
    "https://www.googleapis.com/compute/v1/projects/shifter-test/regions/us-east1/subnetworks/range-b",
  ]
  range_network_zones = ["us-east1-b"]
}

run "shared_nat_enrolls_listed_subnets_not_all_subnetworks" {
  command = plan

  assert {
    condition     = google_compute_router_nat.range_nat[0].source_subnetwork_ip_ranges_to_nat == "LIST_OF_SUBNETWORKS"
    error_message = "The primary-region shared range NAT must enroll an explicit LIST_OF_SUBNETWORKS, never ALL_SUBNETWORKS (ADR-026-R6)."
  }

  # The additional-region bridge NAT (#2029) exists for the pooled region that has
  # a listed subnet, and enrolls it explicitly rather than every subnet.
  assert {
    condition     = google_compute_router_nat.range_nat_extra["us-east1"].source_subnetwork_ip_ranges_to_nat == "LIST_OF_SUBNETWORKS"
    error_message = "The additional-region shared range NAT must enroll an explicit LIST_OF_SUBNETWORKS, never ALL_SUBNETWORKS (ADR-026-R6)."
  }
}

run "zero_egress_steady_state_creates_no_shared_nat" {
  command = plan

  variables {
    shared_range_nat_subnetwork_self_links = []
    range_network_zones                    = ["us-east1-b"]
  }

  assert {
    condition     = length(google_compute_router_nat.range_nat) == 0
    error_message = "With no listed migration-bridge subnets the primary shared NAT must not exist so a zero-egress range gets no NAT path."
  }

  assert {
    condition     = length(google_compute_router_nat.range_nat_extra) == 0
    error_message = "A pooled region with no listed migration-bridge subnets must get no shared NAT (its cells use per-range NAT)."
  }
}

run "primary_region_and_unpooled_subnets_are_not_bridged_to_extra_nat" {
  command = plan

  variables {
    shared_range_nat_subnetwork_self_links = [
      "https://www.googleapis.com/compute/v1/projects/shifter-test/regions/us-central1/subnetworks/range-a",
      "https://www.googleapis.com/compute/v1/projects/shifter-test/regions/us-west1/subnetworks/range-c",
    ]
    range_network_zones = ["us-east1-b"]
  }

  # The primary region (us-central1) is served by its own range_nat; it must never
  # get a duplicate range_nat_extra contending over the same subnet.
  assert {
    condition     = !contains(keys(google_compute_router_nat.range_nat_extra), "us-central1")
    error_message = "The primary region must not receive an extra-region NAT alongside its primary NAT (region != var.region filter)."
  }

  # A listed subnet in a region outside the operator's declared zone pool
  # (us-west1 is not in range_network_zones) is dropped, not bridged.
  assert {
    condition     = !contains(keys(google_compute_router_nat.range_nat_extra), "us-west1")
    error_message = "A listed subnet outside the declared zone pool must not be bridged (contains(range_pool_regions) filter)."
  }
}
