variable "project_id" {
  description = "GCP project that hosts the packer builder subnet and image bucket."
  type        = string
}

variable "name_prefix" {
  description = "Resource name prefix (e.g. shifter-gcp-dev)."
  type        = string
}

variable "region" {
  description = "Region for the packer builder subnet and image bucket."
  type        = string
}

variable "platform_network" {
  description = "Name/self_link of the platform VPC network that hosts the packer builder subnet (has Cloud NAT for egress)."
  type        = string
}

variable "packer_service_account_email" {
  description = "Email of the packer build service account (created in the foundational cicd-oidc root). Granted image-bucket write and used as the IAP firewall target."
  type        = string
}

variable "validation_network_tag" {
  description = "Network tag used only by no-SA disposable image-validation VMs for IAP probes."
  type        = string
  default     = "shifter-validation"
}

variable "build_subnet_cidr" {
  description = "Primary CIDR for the dedicated packer builder subnet."
  type        = string
  default     = "172.16.8.0/28"
}

variable "image_bucket_location" {
  description = "Location for the GDC VM Runtime image bucket (GCE->GCS exports)."
  type        = string
  default     = "us-central1"
}

variable "access_log_bucket_name" {
  description = "Terminal GCS bucket that receives access logs for exported guest images."
  type        = string
}

variable "image_reader_service_accounts" {
  description = "Service accounts granted read on the GDC VM image bucket (GDC VM Runtime image-pull identity). Empty on the default GCE range backend, which never creates the GDC substrate SA."
  type        = list(string)
  default     = []
}
