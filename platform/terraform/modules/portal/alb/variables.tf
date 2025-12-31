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
  description = "Domain name for ACM certificate (e.g., shifter.keplerops.com)"
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

variable "enable_waf" {
  description = "Enable AWS WAF Web ACL for the ALB"
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
