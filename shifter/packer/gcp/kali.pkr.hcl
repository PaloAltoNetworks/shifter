// Kali Linux attacker image for KubeVirt
//
// Builds from the official Kali cloud image (qcow2). Includes kali-linux-headless,
// XFCE + xrdp for RDP access via Guacamole, and security tools.
//
// Boot-time config (hostname, SSH keys) handled by cloud-init at VM launch.

source "qemu" "kali" {
  iso_url          = "https://kali.download/cloud-images/current/kali-linux-2025.1-cloud-genericcloud-amd64.qcow2"
  iso_checksum     = "none"
  disk_image       = true
  use_backing_file = false

  output_directory = "${var.output_directory}/kali"
  vm_name          = "${var.image_prefix}-kali.qcow2"
  format           = "qcow2"
  disk_size        = "30G"
  accelerator      = "kvm"
  cpus             = var.cpus
  memory           = var.memory
  headless         = var.headless

  net_device     = "virtio-net"
  disk_interface = "virtio"

  ssh_username = "kali"
  ssh_password = "kali"
  ssh_timeout  = "10m"

  cd_content = {
    "meta-data" = ""
    "user-data" = <<-EOF
      #cloud-config
      password: kali
      chpasswd: { expire: false }
      ssh_pwauth: true
    EOF
  }
  cd_label = "cidata"

  shutdown_command = "sudo shutdown -P now"
}

build {
  sources = ["source.qemu.kali"]

  // Reuse the same provisioning scripts as the AWS build.
  // base.sh is skipped because it installs SSM agent from .deb (AWS-specific).
  // XFCE/xrdp and kali tools are installed here instead.
  provisioner "shell" {
    scripts = [
      "../scripts/kali/tools.sh",
      "../scripts/kali/claude-code.sh",
    ]
    environment_vars = [
      "DEBIAN_FRONTEND=noninteractive",
    ]
  }

  // Install XFCE + xrdp for RDP access (from base.sh, minus SSM)
  provisioner "shell" {
    inline = [
      "sudo apt-get update",
      "sudo apt-get install -y xfce4 xfce4-goodies xrdp dbus-x11",
      "sudo systemctl enable xrdp",
      "echo 'xfce4-session' | tee ~/.xsession",
    ]
    environment_vars = [
      "DEBIAN_FRONTEND=noninteractive",
    ]
  }

  // Clean cloud-init for fresh run at VM boot
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
    output = "kali-qemu-manifest.json"
  }
}
