variable "environment" {
  description = "Deployment environment (dev, prod, proof); selects the /shifter/<env>/range SSM prefix."
  type        = string
}

variable "tags" {
  description = "Common resource tags."
  type        = map(string)
  default     = {}
}

variable "parameters" {
  description = <<-EOT
    Range topology values published to /shifter/<environment>/range/<key> as the
    cross-stack provisioner-env contract (ADR-044-R6). Keys are the range output
    names; the EKS control plane reads this prefix and maps the values onto the
    provider-neutral provisioner environment. Empty-string values (a disabled
    optional resource, e.g. NGFW) are skipped: SSM String parameters cannot hold
    an empty value, and the EKS consumer defaults an absent key to "".
  EOT
  type        = map(string)
}
