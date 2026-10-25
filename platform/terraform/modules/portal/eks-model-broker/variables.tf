variable "settings" {
  description = "Validated broker transport and exact regional model intent. No credentials."
  type = object({
    enabled                 = bool
    hostname                = string
    admitted_subnets        = list(string)
    tls_secret_name         = string
    control_tls_secret_name = string
    trust_configmap_name    = string
    invocation_models       = map(string)
  })
  validation {
    condition = (
      var.settings.enabled && length(var.settings.invocation_models) > 0 && length(var.settings.invocation_models) <= 32 &&
      length(var.settings.admitted_subnets) > 0 &&
      can(regex("^[a-z0-9][a-z0-9.-]+[a-z0-9]$", var.settings.hostname)) &&
      var.settings.tls_secret_name != "" && var.settings.control_tls_secret_name != "" && var.settings.trust_configmap_name != "" &&
      var.settings.tls_secret_name != var.settings.control_tls_secret_name &&
      alltrue([for name, model in var.settings.invocation_models : can(regex("^[a-z][a-z0-9-]{0,23}$", name)) && can(regex("^anthropic\\.[a-z0-9-]+-v[0-9]+:[0-9]+$", model))])
    )
    error_message = "Broker module requires complete enabled intent and exact regional Anthropic model IDs."
  }
}

variable "cluster_name" {
  description = "Owning EKS cluster name."
  type        = string
}
variable "region" {
  description = "Single approved AWS region for broker and inference."
  type        = string
}
variable "permissions_boundary_arn" {
  description = "Mandatory boundary for all created IAM roles."
  type        = string
}
variable "oidc_provider_arn" {
  description = "Exact EKS IRSA provider ARN."
  type        = string
}
variable "oidc_issuer" {
  description = "Exact EKS OIDC issuer URL."
  type        = string
}
variable "provisioner_subject" {
  description = "Distinct applied provisioner role authorized for enrollment."
  type        = string
}
variable "vpc_id" {
  description = "EKS VPC ID."
  type        = string
}
variable "vpc_cidr" {
  description = "EKS private VPC network."
  type        = string
}
variable "private_subnets" {
  description = "EKS private subnets keyed by stable availability zone."
  type        = map(object({ id = string, cidr = string }))
}
variable "range_vpc_id" {
  description = "Range VPC from its published topology contract."
  type        = string
}
variable "range_vpc_cidr" {
  description = "Range CIDR from its published topology contract."
  type        = string
}
variable "tags" {
  description = "Deployment resource labels."
  type        = map(string)
  default     = {}
}
