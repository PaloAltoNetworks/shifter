variable "cloud_sql_iam_auth" {
  type        = bool
  default     = false
  description = "Operator-selected native SQL runtime authentication from shifter.yaml."
}

variable "openfga_enabled" {
  type        = bool
  default     = false
  description = "Deploy the released private policy service with separate native SQL duties."
  validation {
    condition     = !var.openfga_enabled || var.cloud_sql_iam_auth
    error_message = "The private policy service requires native SQL runtime authentication."
  }
}
