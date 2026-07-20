variable "name_prefix" {
  description = "Prefix for resource names"
  type        = string
}

variable "iam_name_prefix" {
  description = "Prefix for IAM role and instance profile names (defaults to name_prefix)"
  type        = string
  default     = null
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

variable "access_token_validity_hours" {
  description = "Access token validity in hours"
  type        = number
  default     = 1
}

variable "id_token_validity_hours" {
  description = "ID token validity in hours"
  type        = number
  default     = 1
}

variable "tags" {
  description = "Tags to apply to resources"
  type        = map(string)
  default     = {}
}

variable "secrets_kms_key_arn" {
  description = "ARN of the KMS CMK used to encrypt Secrets Manager secrets owned by this module (CKV_AWS_149). Required input — no default."
  type        = string
}

# Client-secret rotation (#159)

variable "portal_asg_name" {
  description = "Name of the portal ASG the rotation Lambda refreshes after writing the new client to the bundle, so containers rehydrate OIDC_RP_CLIENT_ID/SECRET. Empty leaves consumers to pick up the new client on their next deploy."
  type        = string
  default     = ""
}

variable "enable_autoscaling" {
  description = "Whether the portal runs on an ASG (root passes var.enable_autoscaling). Static gate for the rotation Lambda's ASG-refresh IAM policy."
  type        = bool
  default     = false
}

variable "alerts_topic_arn" {
  description = "SNS topic ARN the scheduled rotation reminder publishes to (the portal alerts topic)."
  type        = string
  default     = ""
}

variable "enable_rotation_reminder" {
  description = "Whether to create the scheduled EventBridge reminder that emails the admin when Cognito client-secret rotation is due. Root sets it to alarm_email != \"\"."
  type        = bool
  default     = false
}

variable "cognito_rotation_reminder_days" {
  description = "Cadence (days) of the Cognito client-secret rotation reminder email."
  type        = number
  default     = 180

  validation {
    condition     = var.cognito_rotation_reminder_days >= 1 && var.cognito_rotation_reminder_days <= 365
    error_message = "cognito_rotation_reminder_days must be between 1 and 365."
  }
}

variable "permissions_boundary_arn" {
  description = "Permissions boundary ARN required on CI-created shifter-* roles"
  type        = string
}
