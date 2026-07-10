variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-2"
}

variable "portal_repository_name" {
  description = "Name for the portal ECR repository"
  type        = string
  default     = "shifter-proof-portal"
}

variable "engine_provisioner_repository_name" {
  description = "Name for the engine provisioner ECR repository"
  type        = string
  default     = "shifter-proof-pulumi-provisioner"
}

variable "guacd_repository_name" {
  description = "Name for the guacd ECR repository"
  type        = string
  default     = "shifter-proof-guacd"
}

variable "guacamole_client_repository_name" {
  description = "Name for the guacamole-client ECR repository"
  type        = string
  default     = "shifter-proof-guacamole-client"
}

variable "budget_alert_email" {
  description = "Email address for AWS Budget S3 cost alerts. Set via gitignored local.auto.tfvars or the TF_VARS_PROOF_CORE deploy secret."
  type        = string
  default     = ""

  validation {
    condition     = var.budget_alert_email == "" || can(regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", var.budget_alert_email))
    error_message = "budget_alert_email must be empty or a valid email address."
  }

  validation {
    condition = (
      var.budget_alert_email == "" ||
      (
        !strcontains(lower(var.budget_alert_email), "example.com") &&
        !strcontains(lower(var.budget_alert_email), "your_email")
      )
    )
    error_message = "budget_alert_email must not use example.com or YOUR_EMAIL placeholders."
  }
}
