// GCP builder overrides for the dev Packer environment.
//
// Pass this file alongside dev.pkrvars.hcl when invoking the googlecompute
// source:
//
//     packer build \
//       -var-file=dev.pkrvars.hcl \
//       -var-file=dev-gcp.pkrvars.hcl \
//       -only='googlecompute.kali' \
//       .
//
// The network/subnetwork names below must exist in the target project; the
// packer_builder subnet and its Cloud NAT egress are managed by the
// platform-core Terraform module under modules/platform-core/main.tf.

gcp_project_id = "prod-rwctxzl6shxk"
gcp_zone       = "us-central1-a"
gcp_network    = "shifter-gcp-dev-platform"
gcp_subnetwork = "shifter-gcp-dev-packer-builder"
gcp_machine_type          = "e2-standard-4"
gcp_service_account_email = ""
