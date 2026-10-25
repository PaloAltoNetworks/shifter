# Portal VPC private-services-access teardown contract test.
#
# Proves the Service Networking connection uses deletion_policy REMOVE_PEERING.
# Without it, `terraform destroy` fails on the connection with "Producer
# services (e.g. CloudSQL, Cloud Memstore, etc.) are still using this
# connection" even after Cloud SQL and Memorystore are deleted, and the
# platform network cannot be removed. ABANDON is not an acceptable substitute:
# it leaves the peering in place, which still blocks deleting the network.
#
# Credential-free: mock_provider synthesizes the google provider; `command =
# plan` is sufficient because deletion_policy is a configuration-known value.
# Run with:
#   terraform -chdir=platform/terraform/gcp/modules/portal/vpc test

mock_provider "google" {}

variables {
  project_id                                = "shifter-test"
  region                                    = "us-central1"
  name_prefix                               = "shifter-test"
  gke_subnet_cidr                           = "10.0.0.0/20"
  gke_pods_cidr                             = "10.4.0.0/14"
  gke_services_cidr                         = "10.8.0.0/20"
  gke_provisioner_pods_cidr                 = "10.40.0.0/20"
  gke_pods_secondary_range_name             = "pods"
  gke_services_secondary_range_name         = "services"
  gke_provisioner_pods_secondary_range_name = "provisioner-pods"
  gke_access_pods_cidr                      = "10.48.0.0/20"
  gke_access_pods_secondary_range_name      = "access-pods"
  private_service_range_prefix_length       = 16
  operator_admin_cidrs                      = []
}

run "service_networking_connection_removes_peering_on_destroy" {
  command = plan

  assert {
    condition     = google_service_networking_connection.services.deletion_policy == "REMOVE_PEERING"
    error_message = "The private-services-access connection must use deletion_policy REMOVE_PEERING so destroy releases the producer-held peering and the platform network can be deleted."
  }
}
