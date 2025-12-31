source "amazon-ebs" "ubuntu" {
  ami_name        = "${var.ami_prefix}-ubuntu-{{timestamp}}"
  ami_description = "Ubuntu 22.04 victim with Apache, MySQL, Docker, Claude Code configured for Bedrock"
  instance_type   = var.instance_type
  region          = var.aws_region

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
    Name      = "${var.ami_prefix}-ubuntu"
    Project   = "shifter"
    ManagedBy = "packer"
    BuildDate = "{{timestamp}}"
  }

  run_tags = {
    Name = "packer-builder-ubuntu"
  }
}

build {
  sources = ["source.amazon-ebs.ubuntu"]

  provisioner "shell" {
    scripts = [
      "scripts/ubuntu/base.sh",
      "scripts/ubuntu/services.sh",
      "scripts/ubuntu/tools.sh",
      "scripts/ubuntu/claude-code.sh",
      "scripts/common/cleanup.sh"
    ]
    execute_command = "sudo -S bash -c '{{ .Vars }} {{ .Path }}'"
  }

  post-processor "manifest" {
    output     = "ubuntu-manifest.json"
    strip_path = true
  }
}
