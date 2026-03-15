source "amazon-ebs" "ctf-devbox" {
  ami_name        = "${var.ami_prefix}-ctf-devbox-{{timestamp}}"
  ami_description = "CTF Box 3 - DevBox - Command injection, SSH key hunting, GTFOBins, dual-homed pivot (based on shifter-ubuntu)"
  instance_type   = var.instance_type
  region          = var.aws_region

  shutdown_behavior = "terminate"

  source_ami_filter {
    filters = {
      name                = "${var.ami_prefix}-ubuntu-*"
      root-device-type    = "ebs"
      virtualization-type = "hvm"
    }
    most_recent = true
    owners      = ["self"]
  }

  ssh_username = "ubuntu"

  vpc_id    = var.vpc_id != "" ? var.vpc_id : null
  subnet_id = var.subnet_id != "" ? var.subnet_id : null

  associate_public_ip_address = true

  tags = {
    Name      = "${var.ami_prefix}-ctf-devbox"
    Project   = "shifter"
    ManagedBy = "packer"
    CTFBox    = "3-devbox"
    BuildDate = "{{timestamp}}"
  }

  run_tags = {
    Name = "packer-builder-ctf-devbox"
  }
}

build {
  sources = ["source.amazon-ebs.ctf-devbox"]

  provisioner "shell" {
    scripts = [
      "scripts/ctf/devbox/setup.sh",
      "scripts/common/cleanup.sh"
    ]
    execute_command = "sudo -S bash -c '{{ .Vars }} {{ .Path }}'"
  }

  post-processor "manifest" {
    output     = "ctf-devbox-manifest.json"
    strip_path = true
  }
}
