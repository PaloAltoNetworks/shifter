source "amazon-ebs" "brokenbk" {
  ami_name        = "${var.ami_prefix}-brokenbk-{{timestamp}}"
  ami_description = "Cortex Broken Bank - intentionally vulnerable training application"
  instance_type   = var.instance_type
  region          = var.aws_region

  // Ensure instance is terminated (not just stopped) if Packer exits ungracefully
  shutdown_behavior = "terminate"

  // Official Ubuntu 22.04 LTS from Canonical
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
    Name      = "${var.ami_prefix}-brokenbk"
    Project   = "shifter"
    ManagedBy = "packer"
    BuildDate = "{{timestamp}}"
  }

  run_tags = {
    Name = "packer-builder-brokenbk"
  }
}

build {
  sources = ["source.amazon-ebs.brokenbk"]

  provisioner "shell" {
    scripts = [
      "scripts/brokenbk/base.sh",
      "scripts/brokenbk/app.sh",
      "scripts/common/cleanup.sh"
    ]
    execute_command = "sudo -S bash -c '{{ .Vars }} {{ .Path }}'"
  }

  post-processor "manifest" {
    output     = "brokenbk-manifest.json"
    strip_path = true
  }
}
