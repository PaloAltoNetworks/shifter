# ------------------------------------------------------------------------------
# Required Variables
# ------------------------------------------------------------------------------

variable "name_prefix" {
  description = "Prefix for resource names"
  type        = string
}

variable "environment" {
  description = "Environment name (dev, prod)"
  type        = string
}

variable "tags" {
  description = "Common tags for all resources"
  type        = map(string)
}

# ------------------------------------------------------------------------------
# Optional Variables
# ------------------------------------------------------------------------------

variable "log_retention_days" {
  description = "CloudWatch log retention in days"
  type        = number
  default     = 30
}

variable "noncurrent_version_transition_days" {
  description = "Days before moving noncurrent versions to Glacier"
  type        = number
  default     = 30
}

variable "noncurrent_version_expiration_days" {
  description = "Days before deleting noncurrent versions"
  type        = number
  default     = 90
}
