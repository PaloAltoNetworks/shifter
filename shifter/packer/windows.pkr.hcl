source "amazon-ebs" "windows" {
  ami_name        = "${var.ami_prefix}-windows-{{timestamp}}"
  ami_description = "Windows Server 2022 with XAMPP, IIS, OpenSSH, Claude Code configured for Bedrock"
  instance_type   = var.instance_type
  region          = var.aws_region

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
    Name      = "${var.ami_prefix}-windows"
    Project   = "shifter"
    ManagedBy = "packer"
    BuildDate = "{{timestamp}}"
  }

  run_tags = {
    Name = "packer-builder-windows"
  }
}

build {
  sources = ["source.amazon-ebs.windows"]

  // Base system configuration
  provisioner "powershell" {
    script = "scripts/windows/base.ps1"
  }

  // Install services (XAMPP, IIS, FTP, OpenSSH)
  provisioner "powershell" {
    script = "scripts/windows/services.ps1"
  }

  // Install development tools (Python, Node.js, Git)
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
    output     = "windows-manifest.json"
    strip_path = true
  }
}
