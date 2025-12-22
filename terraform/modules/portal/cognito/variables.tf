variable "name_prefix" {
  description = "Prefix for resource names"
  type        = string
}

variable "environment" {
  description = "Environment name (e.g., prod, dev) - used for logging"
  type        = string
}

variable "log_retention_days" {
  description = "CloudWatch log retention in days"
  type        = number
}

variable "aws_region" {
  description = "AWS region"
  type        = string
}

variable "cognito_domain_prefix" {
  description = "Domain prefix for Cognito hosted UI (must be globally unique)"
  type        = string
}

variable "callback_urls" {
  description = "OAuth callback URLs"
  type        = list(string)
}

variable "logout_urls" {
  description = "OAuth logout URLs"
  type        = list(string)
}

variable "allowed_email_domains" {
  description = "List of allowed email domains for signup (e.g., paloaltonetworks.com)"
  type        = list(string)
}

variable "allowed_emails" {
  description = "List of specific allowed emails (for external users)"
  type        = list(string)
}

variable "deletion_protection" {
  description = "Enable deletion protection on user pool"
  type        = bool
  default     = true
}

variable "tags" {
  description = "Tags to apply to resources"
  type        = map(string)
  default     = {}
}
