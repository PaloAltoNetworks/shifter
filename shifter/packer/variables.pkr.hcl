// All variables are required - no defaults to prevent silent bugs

variable "aws_region" {
  type        = string
  description = "AWS region to build AMI in"
}

variable "instance_type" {
  type        = string
  description = "EC2 instance type for building (recommend t3.large for faster builds)"
}

variable "ami_prefix" {
  type        = string
  description = "Prefix for AMI names"
}

variable "vpc_id" {
  type        = string
  description = "VPC ID to launch builder in (use empty string for default VPC)"
}

variable "subnet_id" {
  type        = string
  description = "Subnet ID to launch builder in (use empty string for default)"
}

// dc-prebaked.pkr.hcl only. These carry defaults (unlike the core build vars
// above) so `packer build -only='*.<kali|ubuntu|windows>'` does not require them;
// packer validates every declared variable for the whole directory regardless of
// the -only target.

variable "dc_domain_name" {
  type        = string
  description = "AD forest domain for the pre-promoted DC (dc-prebaked)"
  default     = "internal.shifter"
}

variable "dc_netbios_name" {
  type        = string
  description = "NetBIOS name for the pre-promoted DC domain (dc-prebaked)"
  default     = "INTSHIFTER"
}

variable "dc_dsrm_password" {
  type        = string
  sensitive   = true
  description = <<-EOT
    DSRM (Directory Services Restore Mode) password baked into the promoted DC
    forest. Generated per build and injected as PKR_VAR_dc_dsrm_password; never
    committed. Defaults empty and promote-bake.ps1 fails closed when empty, so a
    dc-prebaked build without an injected secret refuses to promote.
  EOT
  default     = ""
}

variable "winrm_bootstrap_password" {
  type        = string
  sensitive   = true
  description = <<-EOT
    Windows builds only (windows, dc, dc-prebaked). Throwaway password that the
    builder's user data sets on the built-in Administrator before WinRM starts,
    so Packer never calls ec2:GetPasswordData to fetch the AMI's generated
    password. Generated per build and injected as
    PKR_VAR_winrm_bootstrap_password; never committed. A Windows build without it
    fails validation instead of falling back to GetPasswordData.
  EOT
  default     = ""
  validation {
    condition     = var.winrm_bootstrap_password == "" || can(regex("^[A-Za-z0-9+/=!_-]{16,128}$", var.winrm_bootstrap_password))
    error_message = "The WinRM bootstrap password must be 16 to 128 characters from A-Z, a-z, 0-9 and +/=!_-."
  }
}

variable "dc_content_script" {
  type        = string
  description = <<-EOT
    Optional path to an AD-content seed script staged into the image and run
    post-promotion by finalize.ps1. It accepts a -DnsForwarder parameter. A
    scenario supplies its own seed (for example from a profile var-file kept with
    the scenario); core supplies none, and an empty value bakes a base DC.
  EOT
  default     = ""
}
