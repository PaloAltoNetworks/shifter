// Proof environment GCE Packer variables.
//
// Fill in your target project's IDs before running a build. See
// docs/dev/deploy-secrets.md ("GCP Packer image builds"). Do NOT commit a real
// winrm_bootstrap_password or any secret here — those are injected with -var at
// build time by the CI workflow.

project_id            = "shifter-proof-xxxxxxxx"
zone                  = "us-central1-a"
network               = "default"
subnetwork            = "default"
service_account_email = "packer-builder@shifter-proof-xxxxxxxx.iam.gserviceaccount.com"
image_prefix          = "shifter"
machine_type          = "e2-standard-2"
use_internal_ip       = false
