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
  description = "VPC ID for the runner. Leave empty to auto-resolve the account default VPC when allow_default_vpc = true; otherwise a non-default, runner-isolated VPC is required (ADR-004-R20)."
  type        = string
  default     = ""
}

variable "subnet_id" {
  description = "Subnet ID for the runner. Leave empty to auto-resolve a subnet of the default VPC when allow_default_vpc = true. Otherwise supply a subnet in a non-default, runner-isolated network with outbound egress for GitHub, ECR, SSM, and AWS APIs."
  type        = string
  default     = ""
}

variable "allow_default_vpc" {
  description = <<-EOT
    Opt-in escape hatch (ADR-004-R20). When false (default) the runner stack fails
    closed on account-default-VPC placement, because a range's private_dns_enabled
    interface VPC endpoints can hijack the runner's AWS API resolution. Set true
    only where default-VPC placement is an accepted, documented tradeoff (the
    aws-dev/aws-proof standup today; see the reassessment issue referenced in
    ADR-004-R20). When true and vpc_id/subnet_id are empty, the account default VPC
    and its first subnet are resolved automatically, so no live VPC/subnet IDs are
    committed (ADR-004-R14).
  EOT
  type        = bool
  default     = false
}

variable "create_runner_network" {
  description = <<-EOT
    Provision a dedicated, ADR-004-R20-compliant runner VPC (non-default, NAT-only
    egress, no private-DNS interface endpoints) via modules/github-runner-network
    and place the runner in it. When true, its outputs take precedence over
    vpc_id/subnet_id and allow_default_vpc. This is the automated bootstrap path
    (issue #1433): it removes the need to supply a live vpc_id/subnet_id override
    or opt into the account default VPC. Default false preserves the existing
    operator-supplied-network / default-VPC-opt-in behavior.
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
