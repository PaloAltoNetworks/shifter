source "amazon-ebs" "windows" {
  ami_name        = "${var.ami_prefix}-windows-{{timestamp}}"
  ami_description = "Windows Server 2022 with XAMPP, IIS, OpenSSH, Claude Code configured for Bedrock"
  instance_type   = var.instance_type
  region          = var.aws_region

  // Instance must STOP (not terminate) when sysprep shuts it down
  // so Packer can create the AMI from the stopped instance
  shutdown_behavior = "stop"

  // Don't send stop command - sysprep handles shutdown, Packer waits for stopped state
  disable_stop_instance = true

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
  // The per-build bootstrap password, set by user_data below. Supplying it
  // keeps Packer from calling ec2:GetPasswordData; a missing value fails
  // validation rather than falling back to that call.
  winrm_password = var.winrm_bootstrap_password != "" ? var.winrm_bootstrap_password : file("winrm_bootstrap_password is required for Windows builds")
  // HTTPS with a self-signed listener (created by user_data); Basic auth never
  // crosses the network in clear.
  winrm_use_ssl  = true
  winrm_insecure = true
  winrm_timeout  = "30m"

  // User data to enable WinRM for Packer
  user_data = <<-EOF
    <powershell>
    # Enable WinRM for Packer provisioning
    Set-ExecutionPolicy Unrestricted -Force
    # Set the per-build Administrator password before WinRM accepts connections.
    Set-LocalUser -Name Administrator -Password (ConvertTo-SecureString '${var.winrm_bootstrap_password}' -AsPlainText -Force)

    # Configure WinRM
    winrm quickconfig -quiet
    $cert = New-SelfSignedCertificate -DnsName "packer-builder" -CertStoreLocation Cert:\LocalMachine\My
    New-Item -Path WSMan:\localhost\Listener -Transport HTTPS -Address * -CertificateThumbPrint $cert.Thumbprint -Force
    # Encrypted transport only: drop the plaintext listener quickconfig created.
    Remove-WSManInstance -ResourceURI winrm/config/Listener -SelectorSet @{Address="*";Transport="HTTP"} -ErrorAction SilentlyContinue
    winrm set winrm/config/service '@{AllowUnencrypted="false"}'
    winrm set winrm/config/service/auth '@{Basic="true"}'
    winrm set winrm/config/winrs '@{MaxMemoryPerShellMB="1024"}'

    # Open firewall for WinRM
    netsh advfirewall firewall add rule name="WinRM HTTPS" dir=in action=allow protocol=TCP localport=5986

    # Restart WinRM
    Restart-Service WinRM
    </powershell>
  EOF

  vpc_id    = var.vpc_id != "" ? var.vpc_id : null
  subnet_id = var.subnet_id != "" ? var.subnet_id : null

  associate_public_ip_address = true
  // Packer's temporary security group admits WinRM only from the builder's IP.
  temporary_security_group_source_public_ip = true

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
  // Note: elevated_user required for Add-WindowsCapability to work via WinRM
  provisioner "powershell" {
    elevated_user     = "Administrator"
    elevated_password = var.winrm_bootstrap_password
    script            = "scripts/windows/services.ps1"
  }

  // Install development tools (Python, Node.js, Git)
  provisioner "powershell" {
    script = "scripts/windows/tools.ps1"
  }

  // Install Claude Code
  provisioner "powershell" {
    script = "scripts/windows/claude-code.ps1"
  }

  // Deterministic first-boot DNS via an EC2Launch v2 preReady task (issue #1633).
  // AWS-only; must run before sysprep so the task is captured into the AMI.
  provisioner "powershell" {
    script = "scripts/aws/windows-ec2launch-dns.ps1"
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
