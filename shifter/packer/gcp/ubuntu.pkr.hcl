// Ubuntu 22.04 victim image for KubeVirt
//
// Builds from the official Ubuntu cloud image (qcow2) using the QEMU builder.
// Output is a qcow2 that gets wrapped in a containerDisk and pushed to
// Artifact Registry. Reuses the same provisioning scripts as the AWS build.
//
// Boot-time config (hostname, SSH keys, users) is handled by cloud-init
// at VM launch via KubeVirt's cloudInitNoCloud volume — not baked in.

source "qemu" "ubuntu" {
  iso_url          = "https://cloud-images.ubuntu.com/jammy/current/jammy-server-cloudimg-amd64.img"
  iso_checksum     = "none"
  disk_image       = true
  use_backing_file = false

  output_directory = "${var.output_directory}/ubuntu"
  vm_name          = "${var.image_prefix}-ubuntu.qcow2"
  format           = "qcow2"
  disk_size        = var.disk_size
  accelerator      = "kvm"
  cpus             = var.cpus
  memory           = var.memory
  headless         = var.headless

  net_device   = "virtio-net"
  disk_interface = "virtio"

  ssh_username = "ubuntu"
  ssh_password = "ubuntu"
  ssh_timeout  = "10m"

  // cloud-init seed ISO to enable password auth for Packer SSH
  cd_content = {
    "meta-data" = ""
    "user-data" = <<-EOF
      #cloud-config
      password: ubuntu
      chpasswd: { expire: false }
      ssh_pwauth: true
    EOF
  }
  cd_label = "cidata"

  shutdown_command = "sudo shutdown -P now"
}

build {
  sources = ["source.qemu.ubuntu"]

  // Reuse the same provisioning scripts as the AWS build.
  // Scripts that reference SSM or EC2-specific services are skipped
  // (cloud-init handles base config, no SSM agent needed on KubeVirt).
  provisioner "shell" {
    scripts = [
      "../scripts/ubuntu/services.sh",
      "../scripts/ubuntu/tools.sh",
      "../scripts/ubuntu/claude-code.sh",
    ]
    environment_vars = [
      "DEBIAN_FRONTEND=noninteractive",
    ]
  }

  // Ensure cloud-init will re-run on next boot (clean instance identity)
  provisioner "shell" {
    inline = [
      "sudo cloud-init clean --logs",
      "sudo truncate -s 0 /etc/machine-id",
      "sudo rm -f /var/lib/dbus/machine-id",
    ]
  }

  provisioner "shell" {
    scripts = ["../scripts/common/cleanup.sh"]
  }

  post-processor "manifest" {
    output = "ubuntu-qemu-manifest.json"
  }
}
