// Cortex Broken Bank GCE image — intentionally vulnerable training app on an
// Ubuntu 22.04 base. Reuses the cloud-neutral ../scripts/brokenbk provisioning.
source "googlecompute" "brokenbk" {
  project_id              = var.project_id
  zone                    = var.zone
  machine_type            = var.machine_type
  source_image_family     = "ubuntu-2204-lts"
  source_image_project_id = ["ubuntu-os-cloud"]
  ssh_username            = "packer"

  network               = var.network
  subnetwork            = var.subnetwork
  service_account_email = var.service_account_email
  scopes                = ["https://www.googleapis.com/auth/cloud-platform"]

  use_internal_ip  = var.use_internal_ip
  omit_external_ip = var.use_internal_ip
  use_iap          = var.use_internal_ip

  image_name        = "${var.image_prefix}-brokenbk-{{timestamp}}"
  image_family      = "${var.image_prefix}-brokenbk"
  image_description = "Cortex Broken Bank - intentionally vulnerable training application (GCE)"
  image_labels = {
    project    = "shifter"
    managed-by = "packer"
    image-type = "brokenbk"
  }
}

build {
  sources = ["source.googlecompute.brokenbk"]

  provisioner "shell" {
    scripts = [
      "../scripts/brokenbk/base.sh",
      "../scripts/brokenbk/app.sh",
      "../scripts/common/cleanup.sh",
    ]
    execute_command = "sudo -S bash -c '{{ .Vars }} {{ .Path }}'"
  }

  post-processor "manifest" {
    output     = "brokenbk-manifest.json"
    strip_path = true
  }
}
