# GKE control-plane NetworkPolicy-enforcement contract test (#1295).
#
# Proves the cluster selects an enforcing datapath so the committed default-deny
# NetworkPolicies (platform/k8s/gcp/base/networkpolicies.yaml) are actually
# enforced, not merely admitted and ignored. This is the GCP parity of the
# AWS/EKS assertion that the vpc-cni NetworkPolicy agent is enabled
# (platform/terraform/modules/portal/eks/tests/security.tftest.hcl).
#
# Credential-free: mock_provider synthesizes the google provider; `command =
# plan` is sufficient because the datapath and networking-mode are
# configuration-known values.
# Run with:
#   terraform -chdir=platform/terraform/gcp/modules/portal/gke test

mock_provider "google" {}
mock_provider "google-beta" {}

variables {
  project_id                                = "shifter-test"
  region                                    = "us-central1"
  name_prefix                               = "shifter-test"
  common_labels                             = { project = "shifter", environment = "test" }
  platform_network_id                       = "projects/shifter-test/global/networks/shifter-test-platform"
  gke_subnetwork_id                         = "projects/shifter-test/regions/us-central1/subnetworks/shifter-test-gke"
  gke_pods_secondary_range_name             = "pods"
  gke_services_secondary_range_name         = "services"
  gke_provisioner_pods_secondary_range_name = "provisioner-pods"
  gke_access_pods_secondary_range_name      = "access-pods"
  gke_master_ipv4_cidr                      = "172.16.0.0/28"
  gke_master_authorized_cidrs               = []
  gke_release_channel                       = "REGULAR"
  web_machine_type                          = "e2-standard-4"
  worker_machine_type                       = "e2-standard-4"
  provisioner_machine_type                  = "e2-standard-4"
  access_machine_type                       = "e2-standard-4"
  web_node_count                            = 1
  worker_node_count                         = 1
  provisioner_node_count                    = 1
  access_node_count                         = 1
  node_service_account_email                = "shifter-test-node@shifter-test.iam.gserviceaccount.com"
}

run "network_policy_enforcement_contract" {
  command = plan

  assert {
    condition     = google_container_cluster.platform.datapath_provider == "ADVANCED_DATAPATH"
    error_message = "GKE must select the ADVANCED_DATAPATH (Dataplane V2) provider so the default-deny NetworkPolicies are enforced, not merely rendered."
  }

  assert {
    condition     = google_container_cluster.platform.networking_mode == "VPC_NATIVE"
    error_message = "Dataplane V2 requires a VPC-native cluster; the enforcing datapath is invalid without it."
  }
}

run "untrusted_plugin_sandbox_pool" {
  command = plan

  assert {
    condition = (
      google_container_node_pool.runtime_plugins.node_config[0].sandbox_config[0].type == "GVISOR" &&
      google_container_node_pool.runtime_plugins.node_config[0].image_type == "COS_CONTAINERD" &&
      google_container_node_pool.runtime_plugins.node_config[0].labels["node-restriction.kubernetes.io/shifter-pool"] == "runtime-plugin" &&
      anytrue([for taint in google_container_node_pool.runtime_plugins.node_config[0].taint :
        taint.key == "shifter.dev/runtime-plugin" && taint.value == "true" && taint.effect == "NO_SCHEDULE"
      ])
    )
    error_message = "Tenant plugin code requires the dedicated gVisor sandbox pool and exclusive placement."
  }

  assert {
    condition = (
      google_container_node_pool.runtime_plugins.initial_node_count == 1 &&
      google_container_node_pool.runtime_plugins.autoscaling[0].total_max_node_count == 3
    )
    error_message = "The plugin pool must keep warm capacity and bounded autoscaling."
  }
}

run "shared_pool_pod_range_contract" {
  command = plan

  assert {
    condition = alltrue([
      google_container_node_pool.web.network_config[0].pod_range == var.gke_pods_secondary_range_name,
      google_container_node_pool.workers.network_config[0].pod_range == var.gke_pods_secondary_range_name,
      google_container_node_pool.runtime_plugins.network_config[0].pod_range == var.gke_pods_secondary_range_name,
    ])
    error_message = "Web, worker, and runtime-plugin pools must explicitly use the primary pod range so GKE cannot assign them to a dedicated access or provisioner range."
  }
}
