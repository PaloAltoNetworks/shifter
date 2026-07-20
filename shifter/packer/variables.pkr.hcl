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

# --- scenario bakes (techvault.pkr.hcl / polaris-vm.pkr.hcl) only ---------------
# The scenario sources bake full Docker Compose stacks over the no-inbound AWS
# Session Manager communicator, so they need a larger builder, an SSM-enabled
# instance profile, an encrypted root volume, and (for polaris) the operator-
# supplied private build tarball. Base-image builds ignore all of these.
variable "scenario_instance_type" {
  type        = string
  description = "EC2 instance type for scenario bake builders (the stacks need more RAM than base images; techvault runbook pins r5.2xlarge)."
  default     = "r5.2xlarge"
}

variable "builder_instance_profile" {
  type        = string
  description = "SSM-enabled instance profile name for scenario bake builders (AmazonSSMManagedInstanceCore + read access to the scenario artifact bucket). Required for scenario bakes; empty for base-image builds."
  default     = ""
}

variable "security_group_id" {
  type        = string
  description = "No-inbound, egress-all security group for scenario bake builders. Isolation is enforced here (no inbound rule), not by dropping the builder's public IP. Empty lets Packer create a temporary group (base-image builds)."
  default     = ""
}

variable "root_volume_size" {
  type        = number
  description = "Root EBS volume size (GiB) for scenario bake builders. TechVault's baked stack needs ~100 GiB."
  default     = 100
}

variable "kms_key_id" {
  type        = string
  description = "Optional KMS key id/alias/ARN for the encrypted scenario root volume. Empty uses the account's default EBS encryption key."
  default     = ""
}

variable "aptl_version" {
  type        = string
  description = "aptl-labs wheel version to bake into the TechVault AMI (bake is pinned to a version)."
  default     = "4.1.2"
}

variable "polaris_tarball_s3_uri" {
  type        = string
  description = "s3://bucket/key of the operator-uploaded Polaris build tarball (private scenario content, staged out of band). Required for the polaris-vm bake; empty otherwise."
  default     = ""
}

# --- polaris-dc.pkr.hcl only (the pre-promoted Polaris domain controller) ------
variable "dc_domain_name" {
  type        = string
  description = "AD forest domain for the polaris-dc bake."
  default     = "boreas.local"
}

variable "dc_netbios_name" {
  type        = string
  description = "NetBIOS name for the polaris-dc bake."
  default     = "BOREAS"
}

variable "dc_content_script" {
  type        = string
  description = "Path (relative to shifter/packer) to the AD-content seed staged into the polaris-dc image and run post-promotion by dc-content-seed.ps1."
  default     = "../../scripts/polaris-aws-range/a2_setup.ps1"
}
