variable "project_id" {
  description = "GCP project whose audit configuration this module owns."
  type        = string
}

variable "service" {
  description = "Google API service name, for example aiplatform.googleapis.com."
  type        = string
}

variable "log_types" {
  description = "Data Access log types to enable for the service."
  type        = list(string)

  validation {
    condition     = length(var.log_types) > 0 && alltrue([for log_type in var.log_types : contains(["ADMIN_READ", "DATA_READ", "DATA_WRITE"], log_type)])
    error_message = "log_types must be a non-empty list of ADMIN_READ, DATA_READ, or DATA_WRITE."
  }
}

variable "enabled" {
  description = "Create the audit configuration. False leaves the service on the project's inherited audit configuration."
  type        = bool
  default     = true
}
