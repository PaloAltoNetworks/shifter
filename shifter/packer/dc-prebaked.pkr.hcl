// dc-prebaked: a PRE-PROMOTED Windows Server 2022 domain controller AMI for AWS.
// Promotion runs at bake time (not first boot) so every range boots an
// already-promoted DC with no per-range ~15-20 min promotion, which would
// otherwise dominate time-to-serve (runtime DC promotion is disabled in the
// provisioner: state_helpers._should_promote_dc_at_runtime always returns false).
//
// This is the AWS counterpart to gcp/dc-prebaked.pkr.hcl. The domain and NetBIOS
// name are variables so one template bakes any domain; dev bakes the standard
// internal.shifter / INTSHIFTER DC that /shifter/ami/dc points at. A scenario
// can bake its own directory content by passing its seed as dc_content_script
// (with a profile var-file kept in the scenario); core carries no seed.
//
// Captured UN-SYSPREPPED on purpose: sysprep cannot generalize a promoted DC
// (and the existing dc.pkr.hcl feature-only image is explicitly NOT a valid
// /shifter/ami/dc for the same reason). The built-in Administrator becomes the
// domain Administrator across the promotion reboot with the same password, so
// packer's WinRM reconnect after windows-restart authenticates unchanged.
source "amazon-ebs" "dc-prebaked" {
  ami_name        = "${var.ami_prefix}-dc-prebaked-{{timestamp}}"
  ami_description = "Pre-promoted ${var.dc_domain_name} DC (AWS, un-sysprepped) for /shifter/ami/dc"
  instance_type   = var.instance_type
  region          = var.aws_region

  // Windows Server 2022 Datacenter from Amazon.
  source_ami_filter {
    filters = {
      name                = "Windows_Server-2022-English-Full-Base-*"
      root-device-type    = "ebs"
      virtualization-type = "hvm"
    }
    most_recent = true
    owners      = ["amazon"]
  }

  // WinRM communicator; the per-build bootstrap password carries across the
  // promotion reboot.
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

  user_data = <<-EOF
    <powershell>
    Set-ExecutionPolicy Unrestricted -Force
    # Set the per-build Administrator password before WinRM accepts connections.
    Set-LocalUser -Name Administrator -Password (ConvertTo-SecureString '${var.winrm_bootstrap_password}' -AsPlainText -Force)
    winrm quickconfig -quiet
    $cert = New-SelfSignedCertificate -DnsName "packer-builder" -CertStoreLocation Cert:\LocalMachine\My
    New-Item -Path WSMan:\localhost\Listener -Transport HTTPS -Address * -CertificateThumbPrint $cert.Thumbprint -Force
    # Encrypted transport only: drop the plaintext listener quickconfig created.
    Remove-WSManInstance -ResourceURI winrm/config/Listener -SelectorSet @{Address="*";Transport="HTTP"} -ErrorAction SilentlyContinue
    winrm set winrm/config/service '@{AllowUnencrypted="false"}'
    winrm set winrm/config/service/auth '@{Basic="true"}'
    winrm set winrm/config/winrs '@{MaxMemoryPerShellMB="1024"}'
    netsh advfirewall firewall add rule name="WinRM HTTPS" dir=in action=allow protocol=TCP localport=5986
    Restart-Service WinRM
    </powershell>
  EOF

  vpc_id    = var.vpc_id != "" ? var.vpc_id : null
  subnet_id = var.subnet_id != "" ? var.subnet_id : null

  associate_public_ip_address = true
  // Packer's temporary security group admits WinRM only from the builder's IP.
  temporary_security_group_source_public_ip = true
  pause_before_connecting                   = "1m"

  tags = {
    Name      = "${var.ami_prefix}-dc-prebaked"
    Project   = "shifter"
    ManagedBy = "packer"
    ImageType = "dc-prebaked"
    Domain    = var.dc_domain_name
    BuildDate = "{{timestamp}}"
  }

  run_tags = {
    Name = "packer-builder-dc-prebaked"
  }
}

build {
  sources = ["source.amazon-ebs.dc-prebaked"]

  // Base system configuration (RDP, firewall, WinRM) in the dc role.
  provisioner "powershell" {
    environment_vars = ["PACKER_ROLE=dc"]
    script           = "scripts/windows/base.ps1"
  }

  // OpenSSH (harmless; useful for operator access to the DC).
  provisioner "powershell" {
    elevated_user     = "Administrator"
    elevated_password = var.winrm_bootstrap_password
    environment_vars  = ["PACKER_ROLE=dc"]
    script            = "scripts/windows/services.ps1"
  }

  // Stage the optional AD content seed for finalize.ps1 to run post-promotion.
  provisioner "powershell" {
    except = var.dc_content_script == "" ? ["amazon-ebs.dc-prebaked"] : []
    inline = ["New-Item -ItemType Directory -Force -Path C:\\shifter-build | Out-Null"]
  }
  provisioner "file" {
    except      = var.dc_content_script == "" ? ["amazon-ebs.dc-prebaked"] : []
    source      = var.dc_content_script
    destination = "C:\\shifter-build\\content-seed.ps1"
  }

  // Install AD DS/DNS, disable the firewall, and Install-ADDSForest for the
  // profile's domain with the reboot deferred to the windows-restart below.
  provisioner "powershell" {
    elevated_user     = "Administrator"
    elevated_password = var.winrm_bootstrap_password
    environment_vars = [
      "DC_DOMAIN_NAME=${var.dc_domain_name}",
      "DC_NETBIOS_NAME=${var.dc_netbios_name}",
      // Build-only DSRM secret, generated per build and injected as a sensitive
      // var (never committed). promote-bake.ps1 refuses to promote without it.
      "DC_DSRM_PASSWORD=${var.dc_dsrm_password}",
    ]
    script = "scripts/dc-prebaked/promote-bake.ps1"
  }

  // Apply the deferred promotion reboot; packer reconnects over WinRM as the
  // domain Administrator (same password) once the DC is back up.
  provisioner "windows-restart" {
    restart_timeout = "20m"
  }

  // MUST BE LAST (before the un-sysprepped capture): wait for AD DS, pin the DNS
  // forwarder to AmazonProvidedDNS, run any staged content seed, and strip build
  // artifacts.
  provisioner "powershell" {
    elevated_user     = "Administrator"
    elevated_password = var.winrm_bootstrap_password
    // A content seed may intentionally rotate the built-in Administrator
    // password. The elevated scheduled task still runs finalize.ps1 through its
    // fail-closed cleanup, but Windows reports 16001 when Packer queries the
    // completed task with the superseded credential (as on GCE).
    valid_exit_codes = [0, 16001]
    script           = "scripts/dc-prebaked/finalize.ps1"
  }

  post-processor "manifest" {
    output     = "dc-prebaked-manifest.json"
    strip_path = true
  }
}
