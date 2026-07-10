// Kali Linux Rolling GCE image (kali-linux-headless, sshpass, Caldera, Claude
// Code). GCP has NO public Kali image project (the AWS path uses an AWS
// Marketplace product code), and the official Kali genericcloud disk is not
// GCE-bootable (no Google guest environment -> no metadata SSH, no network), so
// this builder instead starts from the GCE-native debian-12 base and converts
// it to Kali Rolling in its first provisioning script
// (../scripts/kali/gce-debian-to-kali.sh). No imported base image is required.
source "googlecompute" "kali" {
  project_id   = var.project_id
  zone         = var.zone
  machine_type = var.machine_type
  // Build Kali on Google's debian-12 GCE base rather than importing the
  // official Kali genericcloud disk: that disk has no Google guest environment
  // (no metadata SSH-key injection, no GCE network setup), so packer can never
  // connect to it. The debian-12 image is GCE-native, and the first provisioning
  // script (gce-debian-to-kali.sh) converts it to Kali Rolling in place while
  // re-asserting the guest agent, so the captured image stays GCE-bootable.
  source_image_family     = "debian-12"
  source_image_project_id = ["debian-cloud"]
  ssh_username            = "packer"

  // The conversion full-upgrades the base into Kali Rolling and then layers the
  // kali-linux-headless metapackage, Caldera and Claude Code on top, so size the
  // boot disk well above the debian-12 base (10 GB) with install headroom.
  disk_size = 40

  network               = var.network
  subnetwork            = var.subnetwork
  service_account_email = var.service_account_email
  scopes                = ["https://www.googleapis.com/auth/cloud-platform"]

  use_internal_ip  = var.use_internal_ip
  omit_external_ip = var.use_internal_ip
  use_iap          = var.use_internal_ip

  image_name        = "${var.image_prefix}-kali-{{timestamp}}"
  image_family      = "${var.image_prefix}-kali"
  image_description = "Kali Linux Rolling with kali-linux-headless, sshpass, Caldera, Claude Code (GCE)"
  image_labels = {
    project    = "shifter"
    managed-by = "packer"
    image-type = "kali"
  }
}

build {
  sources = ["source.googlecompute.kali"]

  provisioner "shell" {
    scripts = [
      "../scripts/kali/gce-debian-to-kali.sh",
      "../scripts/kali/base.sh",
      "../scripts/kali/tools.sh",
      "../scripts/kali/caldera.sh",
      "../scripts/common/claude-autostart-install.sh",
      "../scripts/kali/claude-code.sh",
      "../scripts/common/cleanup.sh",
      # GCP-only: force cloud-init's NoCloud datasource so GDC VM Runtime
      # guests consume the range userData. Runs last (after cleanup) so it is
      # the final state captured into the image.
      "scripts/gdc-cloudinit-datasource.sh",
    ]
    execute_command = "sudo -S bash -c '{{ .Vars }} {{ .Path }}'"
  }

  post-processor "manifest" {
    output     = "kali-manifest.json"
    strip_path = true
  }
}
