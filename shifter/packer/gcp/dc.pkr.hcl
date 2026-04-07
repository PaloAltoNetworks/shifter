// Windows Server 2022 Domain Controller image for KubeVirt
//
// Same base as the Windows victim image but with:
// - AD DS feature pre-installed (NOT promoted — promotion happens at runtime)
// - DNS feature pre-installed
// - No XAMPP/IIS/FTP victim services
// - DC-specific firewall rules
//
// At runtime, cloudbase-init userdata promotes the DC:
//   Install-ADDSForest -DomainName "yourrange.local" ...

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

  // Install cloudbase-init
  provisioner "powershell" {
    inline = [
      "$url = 'https://cloudbase.it/downloads/CloudbaseInitSetup_Stable_x64.msi'",
      "Invoke-WebRequest -Uri $url -OutFile 'C:\\cloudbase-init.msi'",
      "Start-Process msiexec -ArgumentList '/i C:\\cloudbase-init.msi /qn /norestart' -Wait",
      "Remove-Item 'C:\\cloudbase-init.msi'",
      "",
      "$configFile = 'C:\\Program Files\\Cloudbase Solutions\\Cloudbase-Init\\conf\\cloudbase-init.conf'",
      "(Get-Content $configFile) -replace 'plugins=.*', 'plugins=cloudbaseinit.plugins.common.mtu.MTUPlugin,cloudbaseinit.plugins.common.sethostname.SetHostNamePlugin,cloudbaseinit.plugins.common.localscripts.LocalScriptsPlugin,cloudbaseinit.plugins.common.userdata.UserDataPlugin' | Set-Content $configFile",
      "(Get-Content $configFile) -replace 'metadata_services=.*', 'metadata_services=cloudbaseinit.metadata.services.nocloudservice.NoCloudConfigDriveService' | Set-Content $configFile",
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

  // Pre-install AD DS + DNS features (promotion happens at runtime via userdata)
  provisioner "powershell" {
    inline = [
      "Install-WindowsFeature -Name AD-Domain-Services -IncludeManagementTools",
      "Install-WindowsFeature -Name DNS -IncludeManagementTools",
      "Install-WindowsFeature -Name RSAT-AD-Tools",
    ]
  }

  // Sysprep
  provisioner "powershell" {
    inline = [
      "& 'C:\\Program Files\\Cloudbase Solutions\\Cloudbase-Init\\conf\\Unattend.xml'",
      "C:\\Windows\\System32\\Sysprep\\sysprep.exe /generalize /oobe /shutdown /unattend:'C:\\Program Files\\Cloudbase Solutions\\Cloudbase-Init\\conf\\Unattend.xml'",
    ]
  }

  post-processor "manifest" {
    output = "dc-qemu-manifest.json"
  }
}
