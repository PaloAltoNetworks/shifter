source "amazon-ebs" "ctf-helpdesk" {
  ami_name        = "${var.ami_prefix}-ctf-helpdesk-{{timestamp}}"
  ami_description = "CTF Box 2 - HelpDesk - SMB cred leak, scheduled task abuse"
  instance_type   = var.instance_type
  region          = var.aws_region

  // Instance must STOP for sysprep to create AMI
  shutdown_behavior = "stop"
  disable_stop_instance = true

  source_ami_filter {
    filters = {
      name                = "Windows_Server-2022-English-Full-Base-*"
      root-device-type    = "ebs"
      virtualization-type = "hvm"
    }
    most_recent = true
    owners      = ["amazon"]
  }

  communicator   = "winrm"
  winrm_username = "Administrator"
  winrm_use_ssl  = false
  winrm_insecure = true
  winrm_timeout  = "30m"

  user_data = <<-EOF
    <powershell>
    Set-ExecutionPolicy Unrestricted -Force
    winrm quickconfig -quiet
    winrm set winrm/config/service '@{AllowUnencrypted="true"}'
    winrm set winrm/config/service/auth '@{Basic="true"}'
    winrm set winrm/config/winrs '@{MaxMemoryPerShellMB="1024"}'
    netsh advfirewall firewall add rule name="WinRM HTTP" dir=in action=allow protocol=TCP localport=5985
    Restart-Service WinRM
    </powershell>
  EOF

  vpc_id    = var.vpc_id != "" ? var.vpc_id : null
  subnet_id = var.subnet_id != "" ? var.subnet_id : null

  associate_public_ip_address = true
  pause_before_connecting = "1m"

  tags = {
    Name      = "${var.ami_prefix}-ctf-helpdesk"
    Project   = "shifter"
    ManagedBy = "packer"
    CTFBox    = "2-helpdesk"
    BuildDate = "{{timestamp}}"
  }

  run_tags = {
    Name = "packer-builder-ctf-helpdesk"
  }
}

build {
  sources = ["source.amazon-ebs.ctf-helpdesk"]

  provisioner "powershell" {
    script = "scripts/windows/base.ps1"
  }

  provisioner "powershell" {
    elevated_user     = "Administrator"
    elevated_password = build.Password
    script            = "scripts/ctf/helpdesk/setup.ps1"
  }

  provisioner "powershell" {
    script = "scripts/windows/sysprep.ps1"
  }

  post-processor "manifest" {
    output     = "ctf-helpdesk-manifest.json"
    strip_path = true
  }
}
