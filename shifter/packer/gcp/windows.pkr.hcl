// Windows Server 2022 victim GCE image (XAMPP, IIS, OpenSSH, Claude Code).
//
// The googlecompute builder has no auto-generated Windows password (unlike the
// AWS builder's build.Password), so a transient local admin `packer_user` is
// created by the startup-script metadata using var.winrm_bootstrap_password —
// a per-build secret injected with -var by CI, never committed. The builder VM
// is generalized by GCESysprep (gcp/scripts/windows/sysprep.ps1) and discarded,
// so the credential never persists into the published image.
source "googlecompute" "windows" {
  project_id              = var.project_id
  zone                    = var.zone
  machine_type            = var.machine_type
  source_image_family     = "windows-2022"
  source_image_project_id = ["windows-cloud"]
  disk_size               = 100

  // WinRM over TLS only: encrypted transport on 5986, no plaintext 5985, no
  // Basic-over-HTTP. winrm_insecure skips validation of the builder's
  // self-signed cert (the transport is still encrypted) since the VM is
  // ephemeral and discarded after sysprep.
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

  // Create the build-time WinRM admin and open an HTTPS WinRM listener on first
  // boot. Runs on the builder VM only; sysprep removes it before capture. The
  // listener is bound to a self-signed cert and unencrypted transport is
  // disabled, so the bootstrap password never crosses the wire in cleartext.
  metadata = {
    windows-startup-script-ps1 = local.winrm_https_bootstrap_ps1
  }

  image_name        = "${var.image_prefix}-windows-{{timestamp}}"
  image_family      = "${var.image_prefix}-windows"
  image_description = "Windows Server 2022 with XAMPP, IIS, OpenSSH, Claude Code (GCE)"
  image_labels = {
    project    = "shifter"
    managed-by = "packer"
    image-type = "windows"
  }
}

build {
  sources = ["source.googlecompute.windows"]

  // Base system configuration (RDP, firewall, WinRM hardening)
  provisioner "powershell" {
    script = "../scripts/windows/base.ps1"
  }

  // Install services (XAMPP, IIS, FTP, OpenSSH)
  // elevated_user required for Add-WindowsCapability to work via WinRM
  provisioner "powershell" {
    elevated_user     = "packer_user"
    elevated_password = var.winrm_bootstrap_password
    script            = "../scripts/windows/services.ps1"
  }

  // Install development tools (Python, Node.js, Git)
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
    output     = "windows-manifest.json"
    strip_path = true
  }
}
