// Ubuntu 22.04 victim GCE image (Apache, MySQL, Docker, Claude Code).
// Reuses the cloud-neutral Ubuntu provisioning scripts from ../scripts/ubuntu.
// Guest specialization that is AWS-specific in those scripts (the SSM agent;
// Claude Code's Bedrock binding) is a guest-runtime / range-provisioning
// concern that the #505 preflight scopes OUT; see gcp/README.md for the
// GCP-guest-specialization follow-up.
source "googlecompute" "ubuntu" {
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

  image_name        = "${var.image_prefix}-ubuntu-{{timestamp}}"
  image_family      = "${var.image_prefix}-ubuntu"
  image_description = "Ubuntu 22.04 victim with Apache, MySQL, Docker, Claude Code (GCE)"
  image_labels = {
    project    = "shifter"
    managed-by = "packer"
    image-type = "ubuntu"
  }
}

build {
  sources = ["source.googlecompute.ubuntu"]

  provisioner "shell" {
    scripts = [
      "../scripts/ubuntu/base.sh",
      "../scripts/ubuntu/services.sh",
      "../scripts/ubuntu/tools.sh",
    ]
    execute_command = "sudo -S bash -c '{{ .Vars }} {{ .Path }}'"
  }

  provisioner "shell" {
    script           = "../scripts/ubuntu/desktop.sh"
    valid_exit_codes = [0, 123]
    execute_command  = "sudo -S bash -c '{{ .Vars }} {{ .Path }}'"
  }

  provisioner "shell" {
    inline          = ["test -f /var/tmp/shifter-desktop-ready"]
    execute_command = "sudo -S bash -c '{{ .Vars }} {{ .Path }}'"
  }

  provisioner "shell" {
    scripts = [
      "../scripts/common/claude-autostart-install.sh",
      "../scripts/ubuntu/claude-code.sh",
      "../scripts/common/cleanup.sh",
      # GCP-only: force cloud-init's NoCloud datasource so GDC VM Runtime
      # guests consume the range userData. Runs last (after cleanup) so it is
      # the final state captured into the image.
      "scripts/gdc-cloudinit-datasource.sh",
    ]
    execute_command = "sudo -S bash -c '{{ .Vars }} {{ .Path }}'"
  }

  post-processor "manifest" {
    output     = "ubuntu-manifest.json"
    strip_path = true
  }
}
