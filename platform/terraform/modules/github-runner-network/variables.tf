variable "name_prefix" {
  description = "Prefix for all resource names/tags in the runner network."
  type        = string
  default     = "shifter-github-runner"
}

variable "iam_name_prefix" {
  description = "Optional distinct prefix for IAM resource names (falls back to name_prefix)."
  type        = string
  default     = null
}

variable "vpc_cidr" {
  description = <<-EOT
    CIDR block for the dedicated runner VPC. Split into a NAT (public) subnet and
    a runner (private) subnet via cidrsubnet(cidr, 2, 0|1). Must be a non-default,
    range-isolated range that does not overlap networks the runner peers with.
  EOT
  type        = string
  default     = "10.20.0.0/24"

  validation {
    condition     = can(cidrhost(var.vpc_cidr, 0))
    error_message = "vpc_cidr must be a valid IPv4 CIDR block (e.g. 10.20.0.0/24)."
  }
}

variable "enable_flow_logs" {
  description = "Create VPC flow logs (CloudWatch, KMS-encrypted) for the runner VPC."
  type        = bool
  default     = true
}

variable "flow_log_retention_days" {
  description = "Retention for the runner VPC flow-log CloudWatch group (>= 365 to satisfy CKV_AWS_338)."
  type        = number
  default     = 365
}

variable "tags" {
  description = "Extra tags merged onto every resource."
  type        = map(string)
  default     = {}
}
