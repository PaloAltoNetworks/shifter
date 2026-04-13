// Core AWS variables - no defaults to prevent silent bugs

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
  description = "Prefix for AMI names (also reused as the GCE image family prefix)"
}

variable "vpc_id" {
  type        = string
  description = "VPC ID to launch builder in (use empty string for default VPC)"
}

variable "subnet_id" {
  type        = string
  description = "Subnet ID to launch builder in (use empty string for default)"
}

// GCP variables for the googlecompute source in kali.pkr.hcl and
// ubuntu.pkr.hcl. Defaults intentionally empty so AWS-only invocations
// still pass `packer validate` without needing a GCP project; the GCP
// builds pass `dev-gcp.pkrvars.hcl` (or equivalent) to populate them.

variable "gcp_project_id" {
  type        = string
  description = "GCP project ID the googlecompute builder launches instances into. Default is a placeholder so `packer validate` passes for AWS-only invocations; real GCP builds must override via dev-gcp.pkrvars.hcl or equivalent."
  default     = "shifter-gcp-placeholder"
}

variable "gcp_zone" {
  type        = string
  description = "GCP zone for the Packer builder instance. Default placeholder; override per environment."
  default     = "us-central1-a"
}

variable "gcp_network" {
  type        = string
  description = "GCP VPC network self link or short name for the Packer builder."
  default     = ""
}

variable "gcp_subnetwork" {
  type        = string
  description = "GCP subnetwork self link or short name for the Packer builder."
  default     = ""
}

variable "gcp_machine_type" {
  type        = string
  description = "GCP machine type for the Packer builder instance."
  default     = "e2-standard-4"
}

variable "gcp_service_account_email" {
  type        = string
  description = "Optional service account email to attach to the Packer builder instance. Leave empty to use the project default compute SA."
  default     = ""
}
