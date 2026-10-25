variable "model_broker" {
  description = "Validated deployment-owned model broker transport. Disabled creates no listener or identity."
  type = object({
    enabled                 = optional(bool, false)
    hostname                = optional(string, "")
    vip                     = optional(string, "")
    admitted_subnets        = optional(list(string), [])
    global_access           = optional(bool, false)
    tls_secret_name         = optional(string, "")
    control_tls_secret_name = optional(string, "")
    trust_configmap_name    = optional(string, "")
    model_projects          = optional(map(string), {})
  })
  default = {}

  validation {
    condition = !var.model_broker.enabled || (
      can(cidrnetmask("${var.model_broker.vip}/32"))
      && can(regex("^(10\\.|172\\.(1[6-9]|2[0-9]|3[01])\\.|192\\.168\\.)", var.model_broker.vip))
      && can(regex("^[a-z0-9][a-z0-9.-]+\\.[a-z]{2,63}$", var.model_broker.hostname))
      && length(var.model_broker.admitted_subnets) > 0
      && length(var.model_broker.admitted_subnets) <= 256
      && length(var.model_broker.model_projects) > 0
      && length(var.model_broker.model_projects) <= 32
      && alltrue([for name in [var.model_broker.tls_secret_name, var.model_broker.control_tls_secret_name, var.model_broker.trust_configmap_name] :
      can(regex("^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$", name))])
      && var.model_broker.tls_secret_name != var.model_broker.control_tls_secret_name
      && alltrue([for project, account in var.model_broker.model_projects :
      can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", project)) && can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", account))])
      && alltrue([for cidr in var.model_broker.admitted_subnets :
        can(cidrnetmask(cidr)) && can(regex("^(10\\.|172\\.(1[6-9]|2[0-9]|3[01])\\.|192\\.168\\.)", cidr))
      && try(tonumber(split("/", cidr)[1]) >= 8, false)])
    )
    error_message = "Enabled model broker requires a private VIP, hostname, bounded admitted subnets, distinct TLS references and exact model-project identities."
  }
}
