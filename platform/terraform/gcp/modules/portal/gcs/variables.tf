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

variable "force_destroy" {
  description = "Allow terraform destroy to empty and delete the assets and audit-logs buckets. Default false so a normal apply never risks object loss; the GCP destroy workflow renders this true into an ephemeral tfvars so teardown can remove the (versioned, populated) buckets. Without it, terraform destroy fails with 'Error trying to delete bucket ... without force_destroy set to true'."
  type        = bool
  default     = false
}
