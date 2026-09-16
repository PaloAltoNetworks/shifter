variable "project_id" {
  type        = string
  description = "Existing tenant project hosting private pack objects."
}

variable "bucket_name" {
  type        = string
  description = "Globally unique private pack bucket name."
}

variable "location" {
  type        = string
  description = "Storage location within the tenant's selected region."
}

variable "access_log_bucket_name" {
  type        = string
  description = "Existing terminal GCS bucket that receives private pack access logs."
}

variable "portal_service_account_email" {
  type        = string
  description = "Existing portal identity; receives read-only access to this bucket only."
}
