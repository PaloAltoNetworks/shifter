source "amazon-ebs" "dc" {
  ami_name        = "${var.ami_prefix}-dc-{{timestamp}}"
  ami_description = "Windows Server 2022 Domain Controller with AD DS feature, RDP, OpenSSH, Claude Code"
  instance_type   = var.instance_type
  region          = var.aws_region

  // Ensure instance is terminated (not just stopped) if Packer exits ungracefully
  shutdown_behavior = "terminate"

  // Windows Server 2022 Datacenter from Amazon
  source_ami_filter {
    filters = {
      name                = "Windows_Server-2022-English-Full-Base-*"
      root-device-type    = "ebs"
      virtualization-type = "hvm"
    }
    most_recent = true
    owners      = ["amazon"]
  }

  // WinRM communicator for Windows provisioning
  communicator   = "winrm"
  winrm_username = "Administrator"
  winrm_use_ssl  = false
  winrm_insecure = true
  winrm_timeout  = "30m"

  // User data to enable WinRM for Packer
  user_data = <<-EOF
    <powershell>
    # Enable WinRM for Packer provisioning
    Set-ExecutionPolicy Unrestricted -Force

    # Configure WinRM
    winrm quickconfig -quiet
    winrm set winrm/config/service '@{AllowUnencrypted="true"}'
    winrm set winrm/config/service/auth '@{Basic="true"}'
    winrm set winrm/config/winrs '@{MaxMemoryPerShellMB="1024"}'

    # Open firewall for WinRM
    netsh advfirewall firewall add rule name="WinRM HTTP" dir=in action=allow protocol=TCP localport=5985

    # Restart WinRM
    Restart-Service WinRM
    </powershell>
  EOF

  vpc_id    = var.vpc_id != "" ? var.vpc_id : null
  subnet_id = var.subnet_id != "" ? var.subnet_id : null

  associate_public_ip_address = true

  // Windows needs more time to boot
  pause_before_connecting = "1m"

  tags = {
    Name      = "${var.ami_prefix}-dc"
    Project   = "shifter"
    ManagedBy = "packer"
    BuildDate = "{{timestamp}}"
  }

  run_tags = {
    Name = "packer-builder-dc"
  }
}

build {
  sources = ["source.amazon-ebs.dc"]

  // Base system configuration (RDP, firewall, SSM, AD DS feature)
  provisioner "powershell" {
    environment_vars = ["PACKER_ROLE=dc"]
    script           = "scripts/windows/base.ps1"
  }

  // Install services (OpenSSH only for DC)
  // Note: elevated_user required for Add-WindowsCapability to work via WinRM
  provisioner "powershell" {
    elevated_user     = "Administrator"
    elevated_password = build.Password
    environment_vars  = ["PACKER_ROLE=dc"]
    script            = "scripts/windows/services.ps1"
  }

  // Install development tools (Python, Node.js, Git - needed for Claude Code)
  provisioner "powershell" {
    script = "scripts/windows/tools.ps1"
  }

  // Install Claude Code
  provisioner "powershell" {
    script = "scripts/windows/claude-code.ps1"
  }

  // Sysprep (MUST BE LAST - shuts down instance)
  provisioner "powershell" {
    script = "scripts/windows/sysprep.ps1"
  }

  post-processor "manifest" {
    output     = "dc-manifest.json"
    strip_path = true
  }
}
