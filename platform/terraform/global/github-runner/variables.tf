variable "region" {
  description = "AWS region"
  type        = string
  default     = "us-east-2"
}

variable "environment" {
  description = "Environment name (dev, prod)"
  type        = string
  default     = "dev"
}

variable "vpc_id" {
  description = "VPC ID for the runner"
  type        = string
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
# GitHub App Configuration
# ------------------------------------------------------------------------------

variable "github_app_id" {
  description = "GitHub App ID"
  type        = string
}

variable "github_app_key_ssm_path" {
  description = "SSM Parameter Store path for the GitHub App private key (base64 encoded)"
  type        = string
  default     = "/shifter/github-runner/key-base64"
}

variable "github_app_webhook_secret_ssm_path" {
  description = "SSM Parameter Store path for the GitHub App webhook secret"
  type        = string
  default     = "/shifter/github-runner/webhook-secret"
}

# ------------------------------------------------------------------------------
# Runner Configuration
# ------------------------------------------------------------------------------

variable "runners_maximum_count" {
  description = "Maximum number of concurrent runners"
  type        = number
  default     = 5
}

variable "instance_types" {
  description = "List of EC2 instance types for runners"
  type        = list(string)
  default     = ["t3.large", "t3.xlarge"]
}
