source "amazon-ebs" "ctf-webshell" {
  ami_name        = "${var.ami_prefix}-ctf-webshell-{{timestamp}}"
  ami_description = "CTF Box 0 - WebShell (Walkthrough) - Apache/PHP webshell, SUID privesc"
  instance_type   = var.instance_type
  region          = var.aws_region

  shutdown_behavior = "terminate"

  source_ami_filter {
    filters = {
      name                = "ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*"
      root-device-type    = "ebs"
      virtualization-type = "hvm"
    }
    most_recent = true
    owners      = ["099720109477"] // Canonical
  }

  ssh_username = "ubuntu"

  vpc_id    = var.vpc_id != "" ? var.vpc_id : null
  subnet_id = var.subnet_id != "" ? var.subnet_id : null

  associate_public_ip_address = true

  tags = {
    Name      = "${var.ami_prefix}-ctf-webshell"
    Project   = "shifter"
    ManagedBy = "packer"
    CTFBox    = "0-webshell"
    BuildDate = "{{timestamp}}"
  }

  run_tags = {
    Name = "packer-builder-ctf-webshell"
  }
}

build {
  sources = ["source.amazon-ebs.ctf-webshell"]

  provisioner "shell" {
    scripts = [
      "scripts/ubuntu/base.sh",
      "scripts/ctf/webshell/setup.sh",
      "scripts/common/cleanup.sh"
    ]
    execute_command = "sudo -S bash -c '{{ .Vars }} {{ .Path }}'"
  }

  post-processor "manifest" {
    output     = "ctf-webshell-manifest.json"
    strip_path = true
  }
}
