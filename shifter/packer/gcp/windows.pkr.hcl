// Windows Server 2022 victim image for KubeVirt
//
// Builds from a Windows Server 2022 ISO using the QEMU builder.
// Installs VirtIO drivers (required for KubeVirt disk/network), cloudbase-init
// (Windows cloud-init equivalent for boot-time config), and runs sysprep
// to generalize the image for cloning.
//
// At VM launch time, KubeVirt provides:
// - sysprep volume (Unattend.xml via ConfigMap) for SID regeneration + hostname
// - cloudInitNoCloud volume for userdata scripts (service config, domain join, etc.)
//
// Requires:
// - Windows Server 2022 ISO (provide path via windows_iso_url variable)
// - VirtIO drivers ISO (auto-downloaded from Fedora)

variable "windows_iso_url" {
  type        = string
  description = "Path or URL to Windows Server 2022 ISO"
}

variable "windows_iso_checksum" {
  type        = string
  description = "SHA256 checksum of the Windows ISO"
  default     = "none"
}

variable "virtio_iso_url" {
  type        = string
  description = "URL to VirtIO Windows drivers ISO"
  default     = "https://fedorapeople.org/groups/virt/virtio-win/direct-downloads/stable-virtio/virtio-win.iso"
}

source "qemu" "windows" {
  iso_url      = var.windows_iso_url
  iso_checksum = var.windows_iso_checksum

  output_directory = "${var.output_directory}/windows"
  vm_name          = "${var.image_prefix}-windows.qcow2"
  format           = "qcow2"
  disk_size        = "60G"
  accelerator      = "kvm"
  cpus             = var.cpus
  memory           = 8192
  headless         = var.headless

  disk_interface = "virtio"
  net_device     = "virtio-net"

  // Mount VirtIO drivers ISO as second CD-ROM
  qemuargs = [
    ["-drive", "file=${var.virtio_iso_url},media=cdrom,index=2"],
  ]

  // Autounattend.xml on floppy for unattended install
  floppy_files = [
    "answer_files/windows/Autounattend.xml",
  ]

  communicator = "winrm"
  winrm_username = "Administrator"
  winrm_password = "Packer@Build2024!"
  winrm_timeout  = "30m"

  shutdown_command = "shutdown /s /t 10 /f /d p:4:1"
  shutdown_timeout = "15m"
}

build {
  sources = ["source.qemu.windows"]

  // Install VirtIO guest agent (from mounted ISO)
  provisioner "powershell" {
    inline = [
      "# Install QEMU Guest Agent from VirtIO ISO",
      "$virtioISO = (Get-Volume | Where-Object { $_.FileSystemLabel -eq 'virtio-win*' }).DriveLetter",
      "if (-not $virtioISO) { $virtioISO = 'E' }",
      "Start-Process msiexec -ArgumentList \"/i ${virtioISO}:\\guest-agent\\qemu-ga-x86_64.msi /qn /norestart\" -Wait",
    ]
  }

  // Install cloudbase-init (Windows cloud-init equivalent)
  provisioner "powershell" {
    inline = [
      "# Download and install cloudbase-init",
      "$url = 'https://cloudbase.it/downloads/CloudbaseInitSetup_Stable_x64.msi'",
      "Invoke-WebRequest -Uri $url -OutFile 'C:\\cloudbase-init.msi'",
      "Start-Process msiexec -ArgumentList '/i C:\\cloudbase-init.msi /qn /norestart' -Wait",
      "Remove-Item 'C:\\cloudbase-init.msi'",
      "",
      "# Configure cloudbase-init for NoCloud datasource (KubeVirt compatible)",
      "$configFile = 'C:\\Program Files\\Cloudbase Solutions\\Cloudbase-Init\\conf\\cloudbase-init.conf'",
      "(Get-Content $configFile) -replace 'plugins=.*', 'plugins=cloudbaseinit.plugins.common.mtu.MTUPlugin,cloudbaseinit.plugins.common.sethostname.SetHostNamePlugin,cloudbaseinit.plugins.common.localscripts.LocalScriptsPlugin,cloudbaseinit.plugins.common.userdata.UserDataPlugin' | Set-Content $configFile",
      "(Get-Content $configFile) -replace 'metadata_services=.*', 'metadata_services=cloudbaseinit.metadata.services.nocloudservice.NoCloudConfigDriveService' | Set-Content $configFile",
    ]
  }

  // Reuse existing Windows provisioning scripts (services, tools, etc.)
  provisioner "powershell" {
    scripts = [
      "../scripts/windows/services.ps1",
      "../scripts/windows/tools.ps1",
    ]
    environment_vars = [
      "PACKER_ROLE=victim",
    ]
  }

  // Sysprep — generalize the image (new SID on each VM boot)
  // Uses cloudbase-init's sysprep integration instead of EC2Launch
  provisioner "powershell" {
    inline = [
      "# Run sysprep via cloudbase-init (generalizes SID, prepares for Unattend.xml)",
      "& 'C:\\Program Files\\Cloudbase Solutions\\Cloudbase-Init\\conf\\Unattend.xml'",
      "C:\\Windows\\System32\\Sysprep\\sysprep.exe /generalize /oobe /shutdown /unattend:'C:\\Program Files\\Cloudbase Solutions\\Cloudbase-Init\\conf\\Unattend.xml'",
    ]
  }

  post-processor "manifest" {
    output = "windows-qemu-manifest.json"
  }
}
