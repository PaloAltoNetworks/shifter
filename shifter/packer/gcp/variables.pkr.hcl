// GCE Packer variables (issue #505, PLAT-001.10).
//
// These are intentionally GCP-scoped — project / zone / network / service
// account / image family — and never reuse the AWS variables (aws_region,
// vpc_id, subnet_id) per the #505 architecture preflight. Build-time values
// are supplied via a -var-file (see dev.pkrvars.hcl) and, for the WinRM
// bootstrap secret, via a generated -var at build time (never committed).

variable "project_id" {
  type        = string
  description = "GCP project to build the image in and store it in"
}

variable "zone" {
  type        = string
  description = "GCP zone to launch the builder VM in (e.g. us-central1-a)"
}

variable "network" {
  type        = string
  description = "VPC network self-link or name for the builder VM"
}

variable "subnetwork" {
  type        = string
  description = "Subnetwork self-link or name for the builder VM"
}

variable "service_account_email" {
  type        = string
  description = "Service account the builder VM runs as (cloud-platform scope)"
}

variable "image_prefix" {
  type        = string
  description = "Prefix for image names and image families (e.g. shifter)"
}

variable "machine_type" {
  type        = string
  description = "Builder VM machine type (e.g. e2-standard-2)"
}

variable "use_internal_ip" {
  type        = bool
  description = <<-DESC
    Build without an external IP. When true the builder uses the VM's internal
    IP and IAP tunnelling, so the build network must allow IAP (35.235.240.0/20)
    to the SSH/WinRM port. When false the builder gets an ephemeral external IP.
  DESC
}

variable "winrm_bootstrap_password" {
  type        = string
  sensitive   = true
  description = <<-DESC
    Throwaway password for the build-time WinRM user on Windows/DC builds. The
    googlecompute builder has no auto-generated Windows password (unlike
    amazon-ebs), so a transient local admin is created via the startup-script
    metadata using this value. It is generated per build and injected with -var
    by the CI workflow — NEVER commit a real value. The builder VM is sysprepped
    and discarded, so the credential does not persist into the published image.
  DESC
  default     = ""
}

variable "polaris_stack_bucket" {
  type        = string
  description = <<-DESC
    GCS bucket holding the Polaris docker-compose stack tarball for the
    polaris-vm build. The compose stack lives outside this repo, so it is
    fetched at bake time rather than staged from the source tree. Empty leaves
    the host image range-ready without the stack baked (host-setup.sh warns).
  DESC
  default     = ""
}

variable "polaris_stack_key" {
  type        = string
  description = "GCS object key for the Polaris compose stack tarball (see polaris_stack_bucket)."
  default     = "polaris/stack/polaris-stack.tar.gz"
}

# --- Pre-promoted DC (dc-prebaked) --------------------------------------------
# The dc-prebaked template bakes an already-promoted domain controller so ranges
# boot without a per-range ~15-20 min promotion (time-to-serve). One template
# bakes many DC images: pick a profile var-file in dc-profiles/ (or override
# these). Defaults reproduce the Polaris BOREAS.LOCAL image.

variable "dc_image_purpose" {
  type        = string
  description = <<-DESC
    Purpose slug for a pre-promoted DC image, used in the image name and family
    (<image_prefix>-<purpose>-dc). Each purpose is a distinct, reusable pre-baked
    DC (e.g. "polaris" -> shifter-polaris-dc).
  DESC
  default     = "polaris"
}

variable "dc_domain_name" {
  type        = string
  description = "AD forest domain to promote at bake time (e.g. boreas.local)."
  default     = "boreas.local"
}

variable "dc_netbios_name" {
  type        = string
  description = "AD forest NetBIOS name to promote at bake time (e.g. BOREAS)."
  default     = "BOREAS"
}

variable "dc_content_script" {
  type        = string
  description = <<-DESC
    Path (relative to shifter/packer/gcp) to the AD-content seed script staged
    into the image and run post-promotion by finalize.ps1. It creates the
    scenario's OUs/users/groups/SPNs and sets the CTF Administrator password.
    Accepts a -DnsForwarder parameter. Defaults to the Polaris a2_setup.ps1.
  DESC
  default     = "../../../scripts/polaris-aws-range/a2_setup.ps1"
}
