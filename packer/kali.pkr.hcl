packer {
  required_plugins {
    amazon = {
      version = ">= 1.2.0"
      source  = "github.com/hashicorp/amazon"
    }
  }
}

source "amazon-ebs" "kali" {
  ami_name        = "${var.ami_prefix}-kali-{{timestamp}}"
  ami_description = "Shifter Kali Linux with pentesting tools, sshpass, and Claude Code"
  instance_type   = var.instance_type
  region          = var.aws_region

  # Use Kali Linux from AWS Marketplace
  source_ami_filter {
    filters = {
      name                = "kali-linux-*"
      root-device-type    = "ebs"
      virtualization-type = "hvm"
      architecture        = "x86_64"
    }
    most_recent = true
    owners      = ["aws-marketplace"]
  }

  ssh_username = "kali"

  # Optional: specify VPC/subnet if not using default
  vpc_id    = var.vpc_id != "" ? var.vpc_id : null
  subnet_id = var.subnet_id != "" ? var.subnet_id : null

  # Ensure public IP for SSH access during build
  associate_public_ip_address = true

  tags = {
    Name        = "${var.ami_prefix}-kali"
    Project     = "shifter"
    ManagedBy   = "packer"
    BuildDate   = "{{timestamp}}"
  }

  run_tags = {
    Name = "packer-builder-kali"
  }
}

build {
  sources = ["source.amazon-ebs.kali"]

  provisioner "shell" {
    scripts = [
      "scripts/kali/base.sh",
      "scripts/kali/tools.sh",
      "scripts/kali/claude-code.sh",
      "scripts/common/cleanup.sh"
    ]
    execute_command = "sudo -S bash -c '{{ .Vars }} {{ .Path }}'"
  }

  post-processor "manifest" {
    output     = "kali-manifest.json"
    strip_path = true
  }
}
