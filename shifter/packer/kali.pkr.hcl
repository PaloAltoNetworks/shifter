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
  ami_description = "Kali Linux Rolling (from official Debian 12) with SSM, kali-linux-headless, sshpass, Caldera, Claude Code configured for Bedrock"
  instance_type   = var.instance_type
  region          = var.aws_region

  // Ensure instance is terminated (not just stopped) if Packer exits ungracefully
  shutdown_behavior = "terminate"

  // Official Debian 12 AMI, converted to Kali Rolling in place by
  // scripts/aws/debian-to-kali.sh (#2459). Debian publishes these AMIs directly
  // from its own account with no Marketplace product code, so the resulting image
  // can be exported and published for reuse; an image derived from the
  // Marketplace Kali AMI cannot be exported or made public.
  source_ami_filter {
    filters = {
      name                = "debian-12-amd64-*"
      architecture        = "x86_64"
      root-device-type    = "ebs"
      virtualization-type = "hvm"
    }
    most_recent = true
    owners      = ["136693071363"]
  }

  // The Debian root disk is 8 GiB; Kali Rolling plus the desktop and tool layers
  // need the 25 GiB the range image has always shipped with (#129). cloud-init
  // grows the root filesystem to the volume at the build instance's first boot.
  launch_block_device_mappings {
    device_name           = "/dev/xvda"
    volume_size           = 25
    volume_type           = "gp3"
    delete_on_termination = true
  }

  ssh_username = "admin"

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
      "scripts/aws/debian-to-kali.sh",
      "scripts/kali/base.sh",
      "scripts/aws/linux-resolved-dns.sh",
      "scripts/aws/kali-network-hardening.sh",
      "scripts/kali/tools.sh",
      "scripts/kali/caldera.sh",
      "scripts/common/claude-autostart-install.sh",
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
