// dc-prebaked: a PARAMETERIZED, PRE-PROMOTED Windows Server 2022 domain
// controller image. Promotion runs at bake time (not first boot) so every range
// boots an already-promoted DC with no per-range ~15-20 min promotion, which
// would otherwise dominate time-to-serve. This mirrors the standard Shifter AWS
// range approach.
//
// One template bakes MANY DC images. The domain, NetBIOS name, AD-content seed,
// and image purpose/family are variables (var.dc_domain_name, var.dc_netbios_name,
// var.dc_content_script, var.dc_image_purpose); a profile var-file in
// dc-profiles/ supplies them. Defaults reproduce the Polaris BOREAS.LOCAL image
// (shifter-polaris-dc). See docs/dev/gcp-range-cell-deploy.md for how to bake a
// new-domain DC.
//
// Captured UN-SYSPREPPED on purpose: GCESysprep cannot generalize a promoted DC.
// WinRM is bootstrapped on the built-in Administrator (locals.pkr.hcl
// winrm_https_bootstrap_dc_ps1) so the connection survives the promotion reboot
// (the built-in Administrator becomes the domain Administrator, same password).
// virtio-win drivers and the UEFI fallback bootloader are staged so the same
// image also boots on GDC VM Runtime (GDC binds a virtio NIC and boots OVMF with
// empty NVRAM); both are harmless on GCE.
source "googlecompute" "dc-prebaked" {
  project_id              = var.project_id
  zone                    = var.zone
  machine_type            = var.machine_type
  source_image_family     = "windows-2022"
  source_image_project_id = ["windows-cloud"]
  disk_size               = 100

  communicator   = "winrm"
  winrm_username = "Administrator"
  winrm_password = var.winrm_bootstrap_password
  winrm_insecure = true
  winrm_use_ssl  = true
  winrm_use_ntlm = true
  winrm_timeout  = "30m"

  network               = var.network
  subnetwork            = var.subnetwork
  service_account_email = var.service_account_email
  scopes                = ["https://www.googleapis.com/auth/cloud-platform"]

  use_internal_ip  = var.use_internal_ip
  omit_external_ip = var.use_internal_ip
  use_iap          = var.use_internal_ip

  metadata = {
    windows-startup-script-ps1 = local.winrm_https_bootstrap_dc_ps1
    // Stop the GCE guest agent from resetting the built-in Administrator
    // password that the bootstrap sets (and that packer reconnects with after
    // the promotion reboot). Without this the agent races the bootstrap and
    // WinRM auth fails.
    disable-account-manager = "true"
  }

  image_name        = "${var.image_prefix}-${var.dc_image_purpose}-dc-{{timestamp}}"
  image_family      = "${var.image_prefix}-${var.dc_image_purpose}-dc"
  image_description = "Pre-promoted ${var.dc_domain_name} DC (${var.dc_image_purpose}) with AD content baked in (GCE, un-sysprepped)"
  image_labels = {
    project    = "shifter"
    managed-by = "packer"
    image-type = "${var.dc_image_purpose}-dc"
  }
}

build {
  sources = ["source.googlecompute.dc-prebaked"]

  // Base system configuration (RDP, firewall, WinRM) in the dc role.
  provisioner "powershell" {
    environment_vars = ["PACKER_ROLE=dc"]
    script           = "../scripts/windows/base.ps1"
  }

  // OpenSSH (harmless; useful for operator access to the DC).
  provisioner "powershell" {
    elevated_user     = "Administrator"
    elevated_password = var.winrm_bootstrap_password
    environment_vars  = ["PACKER_ROLE=dc"]
    script            = "../scripts/windows/services.ps1"
  }

  // Stage upstream virtio-win drivers so the image also binds GDC's virtio NIC.
  provisioner "powershell" {
    script = "scripts/dc-prebaked/install-virtio.ps1"
  }

  // Stage the AD content seed for finalize.ps1 to run post-promotion.
  provisioner "powershell" {
    inline = ["New-Item -ItemType Directory -Force -Path C:\\polaris | Out-Null"]
  }
  provisioner "file" {
    source      = var.dc_content_script
    destination = "C:\\polaris\\a2_setup.ps1"
  }

  // Install AD DS/DNS, disable firewall, and Install-ADDSForest for the profile's
  // domain with the reboot deferred to the windows-restart below.
  provisioner "powershell" {
    environment_vars = [
      "DC_DOMAIN_NAME=${var.dc_domain_name}",
      "DC_NETBIOS_NAME=${var.dc_netbios_name}",
    ]
    script = "scripts/dc-prebaked/promote-bake.ps1"
  }

  // Apply the deferred promotion reboot; packer reconnects over WinRM as the
  // domain Administrator once the DC is back up.
  provisioner "windows-restart" {
    restart_timeout = "20m"
  }

  // Post-reboot: wait for AD DS, seed the AD content (dc_content_script).
  // MUST BE LAST — the content seed sets the CTF Administrator password.
  provisioner "powershell" {
    elevated_user     = "Administrator"
    elevated_password = var.winrm_bootstrap_password
    script            = "scripts/dc-prebaked/finalize.ps1"
  }

  post-processor "manifest" {
    output     = "dc-prebaked-manifest.json"
    strip_path = true
  }
}
