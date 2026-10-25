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
    provider-neutral provisioner environment. Include a key only when its
    resource is present — gate optional keys (e.g. NGFW) on the caller's
    plan-known enable flags and omit them otherwise. Never pass "" or null: SSM
    String parameters cannot hold an empty value, and a value-based skip in this
    module would make the for_each key set depend on apply-time values and break
    `terraform plan` on a fresh account. The EKS consumer defaults an absent key
    to "".
  EOT
  type        = map(string)
}
