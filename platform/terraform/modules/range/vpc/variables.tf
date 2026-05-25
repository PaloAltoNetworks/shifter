# Range VPC module variables - NO DEFAULTS

variable "name_prefix" {
  description = "Prefix for resource names (e.g., prod-range)"
  type        = string
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC (e.g., 10.1.0.0/16)"
  type        = string
}

variable "portal_vpc_cidr" {
  description = "CIDR block for the Portal VPC (for SSH access from browser terminal)"
  type        = string
}

variable "tags" {
  description = "Common tags to apply to all resources"
  type        = map(string)
}

# ------------------------------------------------------------------------------
# Network Firewall Configuration
# ------------------------------------------------------------------------------

variable "enable_network_firewall" {
  description = "Enable AWS Network Firewall for egress filtering"
  type        = bool
  default     = true
}

variable "firewall_log_retention_days" {
  description = "CloudWatch log retention for firewall logs"
  type        = number
  default     = 30
}

variable "kali_allowed_domains" {
  description = "Domain allowlist for Kali egress. Empty list means no external access."
  type        = list(string)
  default     = [] # Kali has full tools pre-installed, no external access needed
}

variable "victim_allowed_domains" {
  description = "Domain allowlist for Victim egress (XDR/XSIAM endpoints)"
  type        = list(string)
  default = [
    ".paloaltonetworks.com",
    ".storage.googleapis.com",
    ".pkg.dev",
    "data.pendo.io",
  ]
}

variable "victim_allowed_cidrs" {
  # Implementation detail for the platform-level PLAT-220 range egress allowlist.
  # The public surface is `settings.range_egress.allowed_cidrs` in shifter.yaml
  # (validated by shifter/installation); this AWS module variable is the
  # internal bridge into AWS Network Firewall rule groups. See
  # docs/architecture/range-egress-ip-allowlist.md.
  description = "IP CIDR allowlist for Victim egress (bridge for shifter.yaml settings.range_egress.allowed_cidrs)."
  type        = list(string)
  default     = []

  # Mirrors the public RangeEgressPolicy contract in
  # shifter/installation/range_egress.py: well-formed CIDR (IPv4 or IPv6),
  # parsed prefix length > 0 (rejects 0.0.0.0/0, ::/0, AND alternate spellings
  # like 0.0.0.0/00 that would slip past a literal-string check and otherwise
  # parse as the default route), no host bits set in the network address, no
  # duplicates. `can(cidrhost(...))` accepts both IPv4 and IPv6 (`cidrnetmask`
  # is IPv4-only and would reject IPv6 the public validator accepts).
  validation {
    condition = (
      length(distinct(var.victim_allowed_cidrs)) == length(var.victim_allowed_cidrs)
      && alltrue([
        for c in var.victim_allowed_cidrs : (
          can(cidrhost(c, 0))
          && can(tonumber(split("/", c)[1]))
          && tonumber(split("/", c)[1]) > 0
          && cidrhost(c, 0) == split("/", c)[0]
        )
      ])
    )
    error_message = "victim_allowed_cidrs must be a list of canonical CIDR network addresses (IPv4 or IPv6) with no duplicates; default-route prefixes (parsed prefix length 0, e.g. 0.0.0.0/0, ::/0, 0.0.0.0/00) and host-bits-set inputs are rejected (the platform contract; see docs/architecture/range-egress-ip-allowlist.md)."
  }
}

# ------------------------------------------------------------------------------
# VPC Flow Logs
# ------------------------------------------------------------------------------

variable "enable_flow_logs" {
  description = "Enable VPC flow logs"
  type        = bool
  default     = false
}

# ------------------------------------------------------------------------------
# Range Instance IAM
# ------------------------------------------------------------------------------

variable "agent_s3_bucket" {
  description = "S3 bucket name for agent installers (for range instance S3 read access)"
  type        = string
}

# ------------------------------------------------------------------------------
# VM-Series NGFW Configuration
# ------------------------------------------------------------------------------

variable "vm_series_ami_id" {
  description = "VM-Series AMI ID. Empty string disables NGFW provisioning."
  type        = string
  default     = ""
}

variable "vm_series_instance_type" {
  description = "EC2 instance type for VM-Series NGFW"
  type        = string
  default     = "m5.xlarge"
}

# ------------------------------------------------------------------------------
# Persistent NGFW Infrastructure
# ------------------------------------------------------------------------------

variable "enable_ngfw_infrastructure" {
  description = "Enable persistent NGFW infrastructure (subnet, security groups, IAM role)"
  type        = bool
  default     = false
}
