variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "require_mfa" {
  description = "Require MFA (TOTP) for all users"
  type        = bool
  default     = true
}

variable "authorized_domains" {
  description = "Domains where auth redirects are allowed (e.g., ['shifter.example.com'])"
  type        = list(string)
  default     = []
}

variable "create_oauth_client" {
  description = "Create an OIDC provider config for the portal. Set false if configuring manually."
  type        = bool
  default     = false
}

variable "oauth_client_id" {
  description = "OAuth client ID (if create_oauth_client is true)"
  type        = string
  default     = ""
}

variable "oauth_client_secret" {
  description = "OAuth client secret (if create_oauth_client is true)"
  type        = string
  default     = ""
  sensitive   = true
}
