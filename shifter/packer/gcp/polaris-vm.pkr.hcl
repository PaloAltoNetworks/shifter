// Polaris range-host (polaris-vm) GCE image.
//
// The Polaris participant endpoint is a Kali container inside this Ubuntu/
// Debian Docker host running the polaris docker-compose stack (17 containers
// incl. a14-kali, dns, a9-splice). Built on Google's GCE-native debian-12 base
// (same rationale as kali.pkr.hcl: the base is GCE-bootable with the guest
// agent), then layered with Docker Engine + compose, the Google Cloud SDK, and
// a host sshd moved to the management port so the Kali container can bind host
// :22 / :3389 for participant access.
//
// The full compose stack (docker-compose.yml + build context) lives outside
// this repo (scenario-dev/polaris/build is gitignored, and the AWS polaris-vm
// AMI is likewise baked from an external stack). host-setup.sh fetches the
// stack tarball from GCS at bake time (POLARIS_STACK_BUCKET / POLARIS_STACK_KEY)
// and builds it; when unset it warns and leaves the host otherwise range-ready.
//
// Consumed by the GCE range-cell backend: the deploy points
// GCP_RANGE_KALI_IMAGE at this image family and the scenario's
// `ami_key: polaris-vm` selects the Kali/attacker profile
// (see gcp_range_cell_plan._host_access). The Windows DC uses the generic
// `dc` GCE image family (dc.pkr.hcl); boreas.local is promoted per-range by
// dc_setup, not baked.
source "googlecompute" "polaris-vm" {
  project_id              = var.project_id
  zone                    = var.zone
  machine_type            = var.machine_type
  source_image_family     = "debian-12"
  source_image_project_id = ["debian-cloud"]
  ssh_username            = "packer"

  // Docker Engine plus the multi-container polaris stack needs generous
  // headroom over the debian-12 base (10 GB).
  disk_size = 200

  network               = var.network
  subnetwork            = var.subnetwork
  service_account_email = var.service_account_email
  scopes                = ["https://www.googleapis.com/auth/cloud-platform"]

  use_internal_ip  = var.use_internal_ip
  omit_external_ip = var.use_internal_ip
  use_iap          = var.use_internal_ip

  image_name        = "${var.image_prefix}-polaris-vm-{{timestamp}}"
  image_family      = "${var.image_prefix}-polaris-vm"
  image_description = "Polaris range host: Debian Docker host running the polaris docker-compose stack (GCE)"
  image_labels = {
    project    = "shifter"
    managed-by = "packer"
    image-type = "polaris-vm"
  }
}

build {
  sources = ["source.googlecompute.polaris-vm"]

  // host-setup.sh installs Docker + the Cloud SDK, moves the host sshd to the
  // management port, and (when POLARIS_STACK_BUCKET is set) fetches and builds
  // the compose stack from GCS. The compose stack is not in this repo, so it is
  // supplied at bake time rather than staged from the source tree.
  provisioner "shell" {
    environment_vars = [
      "POLARIS_STACK_BUCKET=${var.polaris_stack_bucket}",
      "POLARIS_STACK_KEY=${var.polaris_stack_key}",
    ]
    scripts = [
      "scripts/polaris/host-setup.sh",
      "../scripts/common/cleanup.sh",
    ]
    execute_command = "sudo -S bash -c '{{ .Vars }} {{ .Path }}'"
  }

  post-processor "manifest" {
    output     = "polaris-vm-manifest.json"
    strip_path = true
  }
}
