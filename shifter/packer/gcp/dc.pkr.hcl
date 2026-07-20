// Windows Server 2022 Domain Controller GCE image (AD DS, RDP, OpenSSH, Claude
// Code). Same build-time WinRM bootstrap and GCESysprep flow as windows.pkr.hcl;
// the PACKER_ROLE=dc env var drives the AD DS branch in the shared scripts.
source "googlecompute" "dc" {
  project_id              = var.project_id
  zone                    = var.zone
  machine_type            = var.machine_type
  source_image_family     = "windows-2022"
  source_image_project_id = ["windows-cloud"]
  disk_size               = 100

  // WinRM over TLS only (see windows.pkr.hcl / locals.pkr.hcl): encrypted
  // transport on 5986, no plaintext 5985, no Basic-over-HTTP. winrm_insecure
  // skips validation of the ephemeral builder's self-signed cert only.
  communicator   = "winrm"
  winrm_username = "packer_user"
  winrm_password = var.winrm_bootstrap_password
  winrm_insecure = true
  winrm_use_ssl  = true
  // NTLM (via Negotiate) instead of packer's default Basic auth: the bootstrap
  // disables Basic on the WinRM service (and GCE's built-in listener defaults to
  // Basic=false too), so Basic auth is rejected and packer otherwise hangs until
  // winrm_timeout. NTLM authenticates the local packer_user over the TLS channel.
  winrm_use_ntlm = true
  winrm_timeout  = "30m"

  network               = var.network
  subnetwork            = var.subnetwork
  service_account_email = var.service_account_email
  scopes                = ["https://www.googleapis.com/auth/cloud-platform"]

  use_internal_ip  = var.use_internal_ip
  omit_external_ip = var.use_internal_ip
  // Tunnel WinRM (5986) through IAP when building without an external IP, so the
  // CI runner reaches the builder's internal IP the same way the Linux builds
  // tunnel SSH. Without this packer connects straight to the unroutable
  // internal IP and hangs until winrm_timeout.
  use_iap = var.use_internal_ip

  // Shared HTTPS WinRM bootstrap (single source of truth in locals.pkr.hcl):
  // self-signed listener on 5986, Basic/unencrypted disabled, only 5986 open.
  metadata = {
    windows-startup-script-ps1 = local.winrm_https_bootstrap_ps1
  }

  image_name        = "${var.image_prefix}-dc-{{timestamp}}"
  image_family      = "${var.image_prefix}-dc"
  image_description = "Windows Server 2022 Domain Controller with AD DS, RDP, OpenSSH, Claude Code (GCE)"
  image_labels = {
    project    = "shifter"
    managed-by = "packer"
    image-type = "dc"
  }
}

build {
  sources = ["source.googlecompute.dc"]

  // Base system configuration (RDP, firewall, WinRM, AD DS feature)
  provisioner "powershell" {
    environment_vars = ["PACKER_ROLE=dc"]
    script           = "../scripts/windows/base.ps1"
  }

  // Install services (OpenSSH only for DC)
  provisioner "powershell" {
    elevated_user     = "packer_user"
    elevated_password = var.winrm_bootstrap_password
    environment_vars  = ["PACKER_ROLE=dc"]
    script            = "../scripts/windows/services.ps1"
  }

  // Install development tools (Python, Node.js, Git - needed for Claude Code)
  provisioner "powershell" {
    script = "../scripts/windows/tools.ps1"
  }

  // Install Claude Code
  provisioner "powershell" {
    script = "../scripts/windows/claude-code.ps1"
  }

  // GCESysprep (MUST BE LAST - generalizes and shuts down the VM)
  provisioner "powershell" {
    script = "scripts/windows/sysprep.ps1"
  }

  post-processor "manifest" {
    output     = "dc-manifest.json"
    strip_path = true
  }
}
