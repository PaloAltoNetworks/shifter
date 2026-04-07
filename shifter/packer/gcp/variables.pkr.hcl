// GCP/KubeVirt Packer variables
//
// Used by QEMU-based builders that produce qcow2 images for KubeVirt.
// These are separate from the AWS variables (variables.pkr.hcl) and
// only used by templates in the gcp/ directory.

variable "image_prefix" {
  type        = string
  description = "Prefix for image names (e.g., 'shifter')"
  default     = "shifter"
}

variable "output_directory" {
  type        = string
  description = "Directory for Packer output qcow2 files"
  default     = "output"
}

variable "disk_size" {
  type        = string
  description = "VM disk size (e.g., '20G', '60G')"
  default     = "20G"
}

variable "cpus" {
  type        = number
  description = "Number of CPUs for the build VM"
  default     = 2
}

variable "memory" {
  type        = number
  description = "Memory in MB for the build VM"
  default     = 4096
}

variable "headless" {
  type        = bool
  description = "Run QEMU in headless mode (no display)"
  default     = true
}

// Artifact Registry target (for containerDisk push)
variable "artifact_registry" {
  type        = string
  description = "Artifact Registry path (e.g., 'us-central1-docker.pkg.dev/my-project/dev-range-vm-images')"
  default     = ""
}
