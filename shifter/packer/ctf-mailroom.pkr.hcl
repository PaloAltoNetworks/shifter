source "amazon-ebs" "ctf-mailroom" {
  ami_name        = "${var.ami_prefix}-ctf-mailroom-{{timestamp}}"
  ami_description = "CTF Box 1 - MailRoom - FTP anon, SSH cred pattern, PATH hijack privesc"
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
    Name      = "${var.ami_prefix}-ctf-mailroom"
    Project   = "shifter"
    ManagedBy = "packer"
    CTFBox    = "1-mailroom"
    BuildDate = "{{timestamp}}"
  }

  run_tags = {
    Name = "packer-builder-ctf-mailroom"
  }
}

build {
  sources = ["source.amazon-ebs.ctf-mailroom"]

  provisioner "shell" {
    scripts = [
      "scripts/ubuntu/base.sh",
      "scripts/ctf/mailroom/setup.sh",
      "scripts/common/cleanup.sh"
    ]
    execute_command = "sudo -S bash -c '{{ .Vars }} {{ .Path }}'"
  }

  post-processor "manifest" {
    output     = "ctf-mailroom-manifest.json"
    strip_path = true
  }
}
