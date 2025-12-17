# Range VPC module variables - NO DEFAULTS

variable "name_prefix" {
  description = "Prefix for resource names (e.g., prod-range)"
  type        = string
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC (e.g., 10.1.0.0/16)"
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
    ".pkg.dev"
  ]
}
