variable "region" {
  description = "AWS region"
  type        = string
  default     = "us-east-2"
}

variable "runner_count" {
  description = "Number of GitHub Actions runners to create"
  type        = number
  default     = 2
}

variable "vpc_id" {
  description = "Existing non-default, runner-isolated VPC for the runner when create_runner_network = false (ADR-004-R20), for example the portal VPC private tier. Supply via a gitignored override, never committed (ADR-004-R14). Ignored when create_runner_network = true. Left empty with the allow_default_vpc exception, the account default VPC is resolved."
  type        = string
  default     = ""
}

variable "subnet_id" {
  description = "Private subnet of var.vpc_id with outbound egress for GitHub, ECR, SSM, and AWS APIs, used when create_runner_network = false (ADR-004-R20). Ignored when create_runner_network = true. Left empty with the allow_default_vpc exception, a default-VPC subnet is resolved."
  type        = string
  default     = ""
}

variable "allow_default_vpc" {
  description = <<-EOT
    Narrow exception to ADR-004-R20. When false (default) the runner stack fails
    closed on account-default-VPC placement, because a range's private_dns_enabled
    interface VPC endpoints can hijack the runner's AWS API resolution. Set true
    only under a documented risk acceptance recorded in docs/adr/exceptions.yaml;
    no tracked environment sets it, and it is never a recovery fallback. Has no
    effect when create_runner_network = true. When true and vpc_id/subnet_id are
    empty, the account default VPC and its first subnet are resolved, so no live
    IDs are committed (ADR-004-R14).
  EOT
  type        = bool
  default     = false
}

variable "create_runner_network" {
  description = <<-EOT
    Provision a dedicated, ADR-004-R20-compliant runner VPC (non-default, NAT-only
    egress, no private-DNS interface endpoints) via modules/github-runner-network
    and place the runner in it. This is the standard placement (issue #1437): the
    tracked dev/proof tfvars and the bootstrap `runners` path set it true. When
    true, its outputs take precedence over vpc_id/subnet_id and allow_default_vpc.
    The false default is deliberate, so supplying vpc_id/subnet_id never also
    creates a VPC; opting out of the standard stays a visible, explicit input.
  EOT
  type        = bool
  default     = false
}

variable "runner_network_cidr" {
  description = "CIDR block for the dedicated runner VPC when create_runner_network = true."
  type        = string
  default     = "10.20.0.0/24"
}

variable "instance_type" {
  description = "EC2 instance type"
  type        = string
  default     = "t3.large"
}

variable "github_org" {
  description = "GitHub organization or username"
  type        = string
  default     = "Brad-Edwards"
}

variable "github_repo" {
  description = "GitHub repository name"
  type        = string
  default     = "shifter"
}

# ------------------------------------------------------------------------------
# Health monitoring (#292)
# ------------------------------------------------------------------------------

variable "alarm_email" {
  description = "Optional email address subscribed to the runner-alerts SNS topic. Empty disables the email subscription; Slack/Teams can subscribe to the topic separately."
  type        = string
  default     = ""
}

variable "enable_system_auto_recovery" {
  description = "Add an EC2 recover action to the StatusCheckFailed_System alarm. Scoped to system status checks (AWS-hardware faults) only; instance-check, CPU, and runner-service alarms always notify rather than auto-act."
  type        = bool
  default     = true
}

variable "cpu_alarm_threshold" {
  description = "Average CPU utilization percent that, when sustained, alarms as a hang proxy."
  type        = number
  default     = 95
}
