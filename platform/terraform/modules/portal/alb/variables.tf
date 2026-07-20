variable "name_prefix" {
  description = "Prefix for resource names"
  type        = string
}

variable "vpc_id" {
  description = "VPC ID"
  type        = string
}

variable "public_subnet_ids" {
  description = "List of public subnet IDs for ALB"
  type        = list(string)
}

variable "domain_name" {
  description = "Domain name for ACM certificate (e.g., shifter.example.com)"
  type        = string
}

variable "app_port" {
  description = "Port the application listens on"
  type        = number
}

variable "health_check_path" {
  description = "Health check path for target group"
  type        = string
}

variable "tags" {
  description = "Tags to apply to resources"
  type        = map(string)
}

variable "enable_stickiness" {
  description = "Enable session stickiness for WebSocket affinity (required for ASG)"
  type        = bool
}

variable "idle_timeout_seconds" {
  description = <<-EOT
    ALB idle timeout in seconds for long-lived WebSocket connections (terminal,
    notification, and Guacamole RDP/SSH traffic share this ALB). Must exceed the
    WebSocket keepalive interval (issue #931). AWS allows 1-4000.
  EOT
  type        = number
  default     = 300

  validation {
    condition     = var.idle_timeout_seconds >= 1 && var.idle_timeout_seconds <= 4000
    error_message = "idle_timeout_seconds must be between 1 and 4000."
  }
}

variable "deregistration_delay_seconds" {
  description = <<-EOT
    Portal target-group deregistration delay in seconds, allowing in-flight
    terminal/WebSocket connections to drain when a target is removed during an
    ASG instance refresh or scale-in (issue #931). AWS allows 0-3600.
  EOT
  type        = number
  default     = 120

  validation {
    condition     = var.deregistration_delay_seconds >= 0 && var.deregistration_delay_seconds <= 3600
    error_message = "deregistration_delay_seconds must be between 0 and 3600."
  }
}

variable "enable_waf" {
  description = "Enable AWS WAF Web ACL for the ALB"
  type        = bool
  default     = true
}

variable "enable_deletion_protection" {
  description = "Enable ALB deletion protection (CKV_AWS_150). Mirrors the `db_deletion_protection` convention: secure default is `true` in prod; dev environments that need intentional teardown set this to `false` and re-apply before destroying."
  type        = bool
  default     = true
}

# ------------------------------------------------------------------------------
# Access Logs
# ------------------------------------------------------------------------------

variable "enable_access_logs" {
  description = "Enable ALB access logs to S3"
  type        = bool
}

variable "logs_bucket_name" {
  description = "S3 bucket name for ALB access logs (required when enable_access_logs is true)"
  type        = string
  default     = ""
}

variable "logs_bucket_policy_id" {
  description = "Optional readiness handle for the S3 bucket policy that permits ALB access-log delivery"
  type        = string
  default     = ""
}

# ------------------------------------------------------------------------------
# WAF Logging
# ------------------------------------------------------------------------------

variable "enable_waf_logging" {
  description = "Enable WAF logging to Firehose"
  type        = bool
  default     = false
}

variable "waf_log_destination_arn" {
  description = "Firehose ARN for WAF logs (must start with aws-waf-logs-)"
  type        = string
  default     = ""
}
