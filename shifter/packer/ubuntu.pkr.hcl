source "amazon-ebs" "ubuntu" {
  ami_name        = "${var.ami_prefix}-ubuntu-{{timestamp}}"
  ami_description = "Ubuntu 22.04 victim with Apache, MySQL, Docker, Claude Code configured for Bedrock"
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
    Name      = "${var.ami_prefix}-ubuntu"
    Project   = "shifter"
    ManagedBy = "packer"
    BuildDate = "{{timestamp}}"
  }

  run_tags = {
    Name = "packer-builder-ubuntu"
  }
}

// GCP googlecompute source. Starts from the official ubuntu-2204-lts image
// family published by ubuntu-os-cloud, same upstream that the AWS AMI
// resolves through Canonical's `ubuntu-jammy-22.04` filter.
source "googlecompute" "ubuntu" {
  project_id              = var.gcp_project_id
  zone                    = var.gcp_zone
  machine_type            = var.gcp_machine_type
  network                 = var.gcp_network
  subnetwork              = var.gcp_subnetwork
  service_account_email   = var.gcp_service_account_email != "" ? var.gcp_service_account_email : null
  source_image_family     = "ubuntu-2204-lts"
  source_image_project_id = ["ubuntu-os-cloud"]
  ssh_username            = "packer"
  use_iap                 = true
  omit_external_ip        = true
  use_internal_ip         = true
  disk_size               = 40

  image_name        = "${var.ami_prefix}-ubuntu-{{timestamp}}"
  image_family      = "${var.ami_prefix}-ubuntu"
  image_description = "Shifter Ubuntu 22.04 range image (Apache, MySQL, Docker, XFCE + xrdp, Claude Code configured for Bedrock)."

  image_labels = {
    project    = "shifter"
    managed_by = "packer"
    role       = "range"
    os         = "ubuntu"
  }

  labels = {
    project    = "shifter"
    managed_by = "packer"
    role       = "packer-builder"
  }

  tags = ["packer-builder"]
}

build {
  sources = [
    "source.amazon-ebs.ubuntu",
    "source.googlecompute.ubuntu",
  ]

  // AWS-only: install amazon-ssm-agent via snap. Requires snapd, which the
  // ubuntu:24.04 pod base and the googlecompute path do not depend on.
  provisioner "shell" {
    only = ["amazon-ebs.ubuntu"]
    scripts = [
      "scripts/ubuntu/aws-ssm.sh"
    ]
    execute_command = "sudo -S bash -c '{{ .Vars }} {{ .Path }}'"
  }

  // Cloud-neutral provisioning.
  provisioner "shell" {
    scripts = [
      "scripts/ubuntu/base.sh",
      "scripts/ubuntu/services.sh",
      "scripts/ubuntu/tools.sh",
      "scripts/ubuntu/desktop.sh",
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
