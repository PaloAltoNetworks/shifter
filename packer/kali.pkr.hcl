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
  ami_description = "Kali Linux Rolling with SSM, kali-linux-headless, sshpass, Claude Code configured for Bedrock"
  instance_type   = var.instance_type
  region          = var.aws_region

  // Official Kali Linux from AWS Marketplace
  // Requires free subscription: https://aws.amazon.com/marketplace/pp/prodview-fznsw3f7mq7to
  // Product code: 7lgvy7mt78lgoi4lant0znp5h
  source_ami_filter {
    filters = {
      product-code        = "7lgvy7mt78lgoi4lant0znp5h"
      root-device-type    = "ebs"
      virtualization-type = "hvm"
    }
    most_recent = true
    owners      = ["aws-marketplace"]
  }

  ssh_username = "kali"

  vpc_id    = var.vpc_id != "" ? var.vpc_id : null
  subnet_id = var.subnet_id != "" ? var.subnet_id : null

  associate_public_ip_address = true

  tags = {
    Name      = "${var.ami_prefix}-kali"
    Project   = "shifter"
    ManagedBy = "packer"
    BuildDate = "{{timestamp}}"
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
