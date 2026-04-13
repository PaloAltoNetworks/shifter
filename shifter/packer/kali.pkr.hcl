packer {
  required_plugins {
    amazon = {
      version = ">= 1.2.0"
      source  = "github.com/hashicorp/amazon"
    }
    googlecompute = {
      version = ">= 1.1.0"
      source  = "github.com/hashicorp/googlecompute"
    }
  }
}

source "amazon-ebs" "kali" {
  ami_name        = "${var.ami_prefix}-kali-{{timestamp}}"
  ami_description = "Kali Linux Rolling with SSM, kali-linux-headless, sshpass, Caldera, Claude Code configured for Bedrock"
  instance_type   = var.instance_type
  region          = var.aws_region

  // Ensure instance is terminated (not just stopped) if Packer exits ungracefully
  shutdown_behavior = "terminate"

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

// GCP googlecompute source. Starts from a stock Debian 12 base; the
// kali-linux-headless metapackage is installed in scripts/kali/tools.sh on
// top, which is how the AWS marketplace Kali AMI also assembles a headless
// Kali footprint from apt. No Kali marketplace image exists on GCP.
source "googlecompute" "kali" {
  project_id              = var.gcp_project_id
  zone                    = var.gcp_zone
  machine_type            = var.gcp_machine_type
  network                 = var.gcp_network
  subnetwork              = var.gcp_subnetwork
  service_account_email   = var.gcp_service_account_email != "" ? var.gcp_service_account_email : null
  source_image_family     = "debian-12"
  source_image_project_id = ["debian-cloud"]
  ssh_username            = "packer"
  use_iap                 = true
  omit_external_ip        = true
  use_internal_ip         = true
  disk_size               = 40

  // Stable GCE image name + family so the secret-manager writer can target
  // projects/<proj>/global/images/family/<family> for the latest build.
  image_name        = "${var.ami_prefix}-kali-{{timestamp}}"
  image_family      = "${var.ami_prefix}-kali"
  image_description = "Shifter Kali range image (Debian 12 + kali-linux-headless, Caldera, Claude Code configured for Bedrock)."

  image_labels = {
    project    = "shifter"
    managed_by = "packer"
    role       = "range"
    os         = "kali"
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
    "source.amazon-ebs.kali",
    "source.googlecompute.kali",
  ]

  // AWS-only: install amazon-ssm-agent for AWS Systems Manager session
  // access. GCP builds skip this via `only =` because they reach the VM
  // over VXLAN+SSH, not SSM.
  provisioner "shell" {
    only = ["amazon-ebs.kali"]
    scripts = [
      "scripts/kali/aws-ssm.sh"
    ]
    execute_command = "sudo -S bash -c '{{ .Vars }} {{ .Path }}'"
  }

  // Cloud-neutral provisioning. Every script in this list must run
  // unchanged on both amazon-ebs and googlecompute sources.
  provisioner "shell" {
    scripts = [
      "scripts/kali/base.sh",
      "scripts/kali/tools.sh",
      "scripts/kali/caldera.sh",
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
