// Windows Server 2022 Domain Controller image for KubeVirt
//
// Pre-promoted DC image — AD forest is fully installed during the Packer build,
// NOT at runtime. This saves 5-10 minutes per range deployment.
//
// CANNOT be sysprepped. Microsoft does not support sysprep on a promoted DC
// (breaks NTDS.dit, replication metadata, SYSVOL). This is the same constraint
// as the AWS DC AMI (prebaked in dc-amis.json with hardcoded AMI IDs).
//
// Implications:
// - Every VM booted from this image has the same SID and computer name
// - This is fine because each range's DC is on an isolated network
// - Must use KubeVirt DataVolume (persistent clone), NOT containerDisk,
//   because AD state needs to persist and the image can't be ephemeral
// - CDI clones the golden DataVolume per range (fast block-level copy)
//
// The domain name and other per-range config are set by the existing
// DC setup plan scripts at range provisioning time (same as AWS flow).

variable "dc_domain_name" {
  type        = string
  description = "AD forest domain name to promote during build"
  default     = "internal.shifter"
}

variable "dc_netbios_name" {
  type        = string
  description = "AD NetBIOS domain name"
  default     = "INTSHIFTER"
}

variable "dc_safe_mode_password" {
  type        = string
  description = "AD DS Safe Mode Administrator password (DSRM)"
  sensitive   = true
}

source "qemu" "dc" {
  iso_url      = var.windows_iso_url
  iso_checksum = var.windows_iso_checksum

  output_directory = "${var.output_directory}/dc"
  vm_name          = "${var.image_prefix}-dc.qcow2"
  format           = "qcow2"
  disk_size        = "60G"
  accelerator      = "kvm"
  cpus             = var.cpus
  memory           = 8192
  headless         = var.headless

  disk_interface = "virtio"
  net_device     = "virtio-net"

  qemuargs = [
    ["-drive", "file=${var.virtio_iso_url},media=cdrom,index=2"],
  ]

  floppy_files = [
    "answer_files/windows/Autounattend.xml",
  ]

  communicator   = "winrm"
  winrm_username = "Administrator"
  winrm_password = var.winrm_password
  winrm_timeout  = "30m"

  shutdown_command = "shutdown /s /t 10 /f /d p:4:1"
  shutdown_timeout = "15m"
}

build {
  sources = ["source.qemu.dc"]

  // Install VirtIO guest agent
  provisioner "powershell" {
    inline = [
      "$virtioISO = (Get-Volume | Where-Object { $_.FileSystemLabel -eq 'virtio-win*' }).DriveLetter",
      "if (-not $virtioISO) { $virtioISO = 'E' }",
      "Start-Process msiexec -ArgumentList \"/i ${virtioISO}:\\guest-agent\\qemu-ga-x86_64.msi /qn /norestart\" -Wait",
    ]
  }

  // Install cloudbase-init (for boot-time hostname/network config — NOT sysprep)
  provisioner "powershell" {
    inline = [
      "$url = 'https://cloudbase.it/downloads/CloudbaseInitSetup_Stable_x64.msi'",
      "Invoke-WebRequest -Uri $url -OutFile 'C:\\cloudbase-init.msi'",
      "Start-Process msiexec -ArgumentList '/i C:\\cloudbase-init.msi /qn /norestart' -Wait",
      "Remove-Item 'C:\\cloudbase-init.msi'",
      "",
      "$configFile = 'C:\\Program Files\\Cloudbase Solutions\\Cloudbase-Init\\conf\\cloudbase-init.conf'",
      "(Get-Content $configFile) -replace 'plugins=.*', 'plugins=cloudbaseinit.plugins.common.mtu.MTUPlugin,cloudbaseinit.plugins.common.localscripts.LocalScriptsPlugin,cloudbaseinit.plugins.common.userdata.UserDataPlugin' | Set-Content $configFile",
      "(Get-Content $configFile) -replace 'metadata_services=.*', 'metadata_services=cloudbaseinit.metadata.services.nocloudservice.NoCloudConfigDriveService' | Set-Content $configFile",
      "",
      "# Remove SetHostNamePlugin — hostname changes break AD on a promoted DC",
    ]
  }

  // Reuse existing Windows scripts with DC role
  provisioner "powershell" {
    scripts = [
      "../scripts/windows/base.ps1",
      "../scripts/windows/tools.ps1",
    ]
    environment_vars = [
      "PACKER_ROLE=dc",
    ]
  }

  // Install AD DS + DNS features
  provisioner "powershell" {
    inline = [
      "Install-WindowsFeature -Name AD-Domain-Services -IncludeManagementTools",
      "Install-WindowsFeature -Name DNS -IncludeManagementTools",
      "Install-WindowsFeature -Name RSAT-AD-Tools",
    ]
  }

  // Promote to Domain Controller (full forest install)
  // This is what makes the image pre-promoted — saves 5-10 min per range.
  provisioner "powershell" {
    inline = [
      "Import-Module ADDSDeployment",
      "$safePwd = ConvertTo-SecureString '${var.dc_safe_mode_password}' -AsPlainText -Force",
      "Install-ADDSForest `",
      "  -DomainName '${var.dc_domain_name}' `",
      "  -DomainNetbiosName '${var.dc_netbios_name}' `",
      "  -SafeModeAdministratorPassword $safePwd `",
      "  -InstallDns:$true `",
      "  -NoRebootOnCompletion:$true `",
      "  -Force:$true",
    ]
  }

  // Reboot after promotion (AD DS requires it)
  provisioner "windows-restart" {
    restart_timeout = "15m"
  }

  // Verify AD is running
  provisioner "powershell" {
    inline = [
      "Get-ADDomain | Select-Object -Property DNSRoot, NetBIOSName, DomainMode",
      "Get-Service NTDS, DNS | Format-Table Name, Status",
    ]
  }

  // NO SYSPREP — cannot sysprep a promoted DC.
  // Image is used as-is. Each range gets a CDI DataVolume clone.
  // Clean up temp files only.
  provisioner "powershell" {
    inline = [
      "Remove-Item -Path $env:TEMP\\* -Recurse -Force -ErrorAction SilentlyContinue",
      "Clear-EventLog -LogName Application, System -ErrorAction SilentlyContinue",
    ]
  }

  post-processor "manifest" {
    output = "dc-qemu-manifest.json"
  }
}
