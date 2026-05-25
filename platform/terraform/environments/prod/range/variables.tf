# Environment variables - NO DEFAULTS

variable "environment" {
  description = "Environment name (e.g., prod, dev)"
  type        = string
}

variable "aws_region" {
  description = "AWS region"
  type        = string
}

variable "vpc_cidr" {
  description = "CIDR block for the Range VPC (e.g., 10.1.0.0/16)"
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
# Phase 5: Additional Log Sources
# ------------------------------------------------------------------------------

variable "enable_flow_logs" {
  description = "Enable VPC flow logs"
  type        = bool
}

variable "log_retention_days" {
  description = "CloudWatch log retention in days"
  type        = number
  default     = 90
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
}

# ------------------------------------------------------------------------------
# Network Firewall IP Allowlist
# ------------------------------------------------------------------------------

variable "victim_allowed_cidrs" {
  # Implementation detail for the platform-level PLAT-220 range egress allowlist.
  # The public surface is `settings.range_egress.allowed_cidrs` in shifter.yaml.
  # Operator writes the per-deployment list into a gitignored `local.auto.tfvars`
  # alongside this directory; the committed baseline ships empty so the repo
  # never holds an operator-specific list. See
  # docs/architecture/range-egress-ip-allowlist.md.
  description = "IP CIDR allowlist for Victim egress (bridge for shifter.yaml settings.range_egress.allowed_cidrs)."
  type        = list(string)
  default     = []

  # Mirrors the public RangeEgressPolicy contract; see the same validation in
  # the underlying module (`platform/terraform/modules/range/vpc/variables.tf`)
  # and the public surface (`shifter/installation/range_egress.py`). The prefix
  # length is parsed numerically so alternate /0 spellings (e.g. 0.0.0.0/00)
  # cannot slip past a literal-string check.
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
    error_message = "victim_allowed_cidrs must be a list of canonical CIDR network addresses (IPv4 or IPv6) with no duplicates; default-route prefixes (parsed prefix length 0) and host-bits-set inputs are rejected."
  }
}
