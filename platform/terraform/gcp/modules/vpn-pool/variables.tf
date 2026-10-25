variable "project_id" {
  description = "Project that hosts the pool."
  type        = string
}

variable "region" {
  description = "Region of the pool, its load balancer and its subnet."
  type        = string
}

variable "zones" {
  description = "Zones the regional instance group spreads servers across. Empty uses up to three available zones of the region."
  type        = list(string)
  default     = []
}

variable "name_prefix" {
  description = "Resource name prefix, for example shifter-<environment>."
  type        = string
}

variable "common_labels" {
  description = "Labels applied to labelable resources."
  type        = map(string)
  default     = {}
}

variable "network_id" {
  description = "Self link or id of the range VPC the pool joins."
  type        = string
}

variable "network_name" {
  description = "Name of the range VPC (firewall rules attach by name)."
  type        = string
}

variable "subnet_cidr" {
  description = "Pool subnet. Ranges admit this network to their participant target only."
  type        = string
}

variable "range_network_cidr" {
  description = "Range network the pool may reach on the participant channels."
  type        = string
}

variable "public_hostname" {
  description = "Portal hostname; the controller calls https://<hostname> with audience https://<hostname>/vpn-control."
  type        = string

  validation {
    condition     = length(trimspace(var.public_hostname)) > 0
    error_message = "The OpenVPN pool needs the portal public hostname."
  }
}

variable "portal_ingress_ip" {
  description = "Portal public ingress address, the only HTTPS destination outside Google APIs."
  type        = string
}

variable "artifact_registry_location" {
  description = "Artifact Registry location of the openvpn repository."
  type        = string
}

variable "artifact_repository" {
  description = "Artifact Registry repository id that holds the openvpn image."
  type        = string
}

variable "deploy_service_account_email" {
  description = "Deploy identity that runs Terraform; it may act as the pool SA only."
  type        = string
}

variable "provisioner_service_account_email" {
  description = "Provisioner identity, the only reader of the tenant CA."
  type        = string
}

variable "machine_type" {
  description = "Server machine type. One OpenVPN process uses one core."
  type        = string
  default     = "e2-standard-2"
}

variable "min_vms" {
  description = "Minimum servers (capacity profile)."
  type        = number

  validation {
    condition     = var.min_vms >= 2
    error_message = "min_vms must be at least 2 so one server can fail or be replaced."
  }
}

variable "max_vms" {
  description = "Maximum servers (capacity profile)."
  type        = number
}

variable "cpu_target_pct" {
  description = "Autoscaler CPU target in percent of the VM."
  type        = number
  default     = 30
}

variable "max_clients_per_vm" {
  description = "OpenVPN max-clients on each server."
  type        = number
  default     = 250
}

variable "tunnel_network" {
  description = "Client address pool inside each server's own network namespace; masqueraded, never routed in the VPC."
  type        = string
  default     = "100.96.0.0/22"

  validation {
    condition     = can(cidrhost(var.tunnel_network, 0)) && tonumber(split("/", var.tunnel_network)[1]) >= 16 && tonumber(split("/", var.tunnel_network)[1]) <= 24
    error_message = "tunnel_network must be an IPv4 CIDR between /16 and /24."
  }
}

variable "health_port" {
  description = "Controller health endpoint port."
  type        = number
  default     = 8080
}

variable "vpc_flow_logs" {
  description = "#2535 range audit telemetry: flow-log settings for the pool subnet, from settings.range_telemetry.vpc_flow_logs."
  type = object({
    enabled              = optional(bool, true)
    aggregation_interval = optional(string, "INTERVAL_5_SEC")
    flow_sampling        = optional(number, 0.5)
    metadata             = optional(string, "INCLUDE_ALL_METADATA")
  })
  default  = {}
  nullable = false
}

variable "nat_logs" {
  description = "#2535 range audit telemetry: Cloud NAT logging for the pool NAT, from settings.range_telemetry.nat_logs."
  type = object({
    enabled = optional(bool, true)
    filter  = optional(string, "ALL")
  })
  default  = {}
  nullable = false
}
