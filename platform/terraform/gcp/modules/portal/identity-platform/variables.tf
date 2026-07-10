variable "project_id" {
  type = string
}

variable "region" {
  type = string
}

variable "name_prefix" {
  type = string
}

variable "identity_authorized_domains" {
  type = list(string)
}

variable "identity_allowed_email_domain" {
  type = string
}

variable "identity_allowed_emails" {
  type = list(string)
}

variable "assets_bucket_name" {
  type = string
}

variable "enable_identity_blocking_function" {
  type        = bool
  default     = true
  description = <<-EOT
    Deploy the gen1 beforeCreate blocking function that enforces the sign-up
    domain allowlist at the Identity Platform layer. Requires an `allUsers`
    Cloud Functions invoker binding (GCIP invokes it unauthenticated), so set
    this to false in projects under a Domain Restricted Sharing org policy that
    forbids public IAM members. When false, the portal application still enforces
    the allowlist fail-closed at login.
  EOT
}
