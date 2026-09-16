variable "project_id" {
  type = string
}

variable "region" {
  type = string
}

variable "environment" {
  type = string
}

variable "common_labels" {
  type = map(string)
}

variable "enable_gcs_usage_log_delivery" {
  description = "Grant the Google-managed group cloud-storage-analytics@google.com objectCreator on the audit-logs bucket for GCS usage-log delivery. Must be false in organizations whose Domain Restricted Sharing policy (iam.allowedPolicyMemberDomains) does not permit the google.com customer, where the binding fails with Error 412. Cloud Audit Logs are unaffected."
  type        = bool
  default     = true
}

variable "public_hostname" {
  type        = string
  default     = ""
  description = "Portal public hostname; when set, the assets bucket allows CORS from https://<hostname> for browser signed-URL uploads/downloads."
}
