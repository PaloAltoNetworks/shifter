# Environment variables - NO DEFAULTS

# ------------------------------------------------------------------------------
# General
# ------------------------------------------------------------------------------

variable "environment" {
  description = "Environment name (e.g., prod, dev)"
  type        = string
}

variable "aws_region" {
  description = "AWS region"
  type        = string
}

variable "log_retention_days" {
  description = "CloudWatch log retention in days"
  type        = number
}

variable "tags" {
  description = "Common tags to apply to all resources"
  type        = map(string)
}

# ------------------------------------------------------------------------------
# VPC
# ------------------------------------------------------------------------------

variable "vpc_cidr" {
  description = "CIDR block for the VPC"
  type        = string
}

variable "az_count" {
  description = "Number of availability zones to use"
  type        = number
}

variable "enable_nat_gateway" {
  description = "Whether to create a NAT gateway for private subnet internet access"
  type        = bool
}

# ------------------------------------------------------------------------------
# RDS
# ------------------------------------------------------------------------------

variable "db_name" {
  description = "Name of the database to create"
  type        = string
}

variable "db_username" {
  description = "Master username for the database"
  type        = string
}

variable "db_engine_version" {
  description = "PostgreSQL engine version"
  type        = string
}

variable "db_instance_class" {
  description = "RDS instance class"
  type        = string
}

variable "db_allocated_storage" {
  description = "Initial allocated storage in GB"
  type        = number
}

variable "db_max_allocated_storage" {
  description = "Maximum storage for autoscaling in GB"
  type        = number
}

variable "db_multi_az" {
  description = "Enable Multi-AZ deployment"
  type        = bool
}

variable "db_backup_retention_days" {
  description = "Number of days to retain backups"
  type        = number
}

variable "db_deletion_protection" {
  description = "Enable deletion protection"
  type        = bool
}

variable "db_skip_final_snapshot" {
  description = "Skip final snapshot on deletion"
  type        = bool
}

variable "db_apply_immediately" {
  description = "Apply portal RDS modifications during the deploy instead of queueing them for the maintenance window."
  type        = bool
}

# ------------------------------------------------------------------------------
# EC2
# ------------------------------------------------------------------------------

variable "ec2_ami_id" {
  description = "AMI ID for portal EC2 instances (use standard AL2023, not ECS-optimized)"
  type        = string
}

variable "ec2_instance_type" {
  description = "EC2 instance type for Django portal"
  type        = string
}

variable "ec2_root_volume_size" {
  description = "Size of EC2 root volume in GB"
  type        = number
}

# ECR values come from terraform_remote_state.foundation

# ------------------------------------------------------------------------------
# ALB
# ------------------------------------------------------------------------------

variable "domain_name" {
  description = "Domain name for ACM certificate (e.g., shifter.example.com)"
  type        = string
}

variable "app_port" {
  description = "Port the Django application listens on"
  type        = number
}

variable "health_check_path" {
  description = "Health check path for ALB target group"
  type        = string
}

# ------------------------------------------------------------------------------
# Cognito
# ------------------------------------------------------------------------------

variable "cognito_domain_prefix" {
  description = "Domain prefix for Cognito hosted UI (must be globally unique)"
  type        = string
}

variable "allowed_email_domains" {
  description = "List of allowed email domains for signup"
  type        = list(string)
}

variable "allowed_emails" {
  description = "List of specific allowed emails (for external users)"
  type        = list(string)
}

# ------------------------------------------------------------------------------
# S3
# ------------------------------------------------------------------------------

variable "user_storage_bucket" {
  description = "S3 bucket name for user file storage (must be globally unique)"
  type        = string
}

# ------------------------------------------------------------------------------
# Provisioner
# ------------------------------------------------------------------------------

variable "victim_instance_type" {
  description = "Instance type for victim EC2 instances"
  type        = string
}

variable "kali_instance_type" {
  description = "Instance type for Kali EC2 instances"
  type        = string
}

# ------------------------------------------------------------------------------
# Autoscaling
# ------------------------------------------------------------------------------

variable "enable_autoscaling" {
  description = "Enable Auto Scaling Group instead of single EC2 instance"
  type        = bool
}

variable "enable_redis" {
  description = <<-EOT
    Wire Redis as the Django Channels backend for the portal runtime
    (ADR-018, #849). Environment-owned and INDEPENDENT of enable_autoscaling:
    a single-instance dev portal may use Redis, and an environment may disable
    Redis to save cost without changing ASG posture. When true, the Redis
    endpoint is published to SSM and the container runs with
    CHANNEL_LAYER_BACKEND=redis (fail-closed if the endpoint is missing); when
    false, the portal runs CHANNEL_LAYER_BACKEND=in_memory.
  EOT
  type        = bool
}

variable "asg_min_size" {
  description = "Minimum number of instances in the ASG"
  type        = number
}

variable "asg_max_size" {
  description = "Maximum number of instances in the ASG"
  type        = number
}

variable "asg_desired_capacity" {
  description = "Desired number of instances in the ASG"
  type        = number
}

variable "scale_up_threshold" {
  description = "CPU percentage threshold to trigger scale up"
  type        = number
}

variable "scale_down_threshold" {
  description = "CPU percentage threshold to trigger scale down"
  type        = number
}

# ------------------------------------------------------------------------------
# Redis
# ------------------------------------------------------------------------------

variable "redis_node_type" {
  description = "ElastiCache Redis node type"
  type        = string
}

variable "redis_engine_version" {
  description = "ElastiCache Redis engine version"
  type        = string
}

variable "redis_enable_replication" {
  description = "Enable Redis replication with automatic failover"
  type        = bool
}

# ------------------------------------------------------------------------------
# Logging
# ------------------------------------------------------------------------------

variable "log_level" {
  description = "Django log level (DEBUG, INFO, WARNING, ERROR). Use DEBUG in dev for detailed event tracing."
  type        = string
  default     = "INFO"
}

# ------------------------------------------------------------------------------
# Log Aggregation
# ------------------------------------------------------------------------------

variable "enable_log_aggregation" {
  description = "Enable log aggregation infrastructure (S3, SQS, Firehose)"
  type        = bool
}

# ------------------------------------------------------------------------------
# Phase 5: Additional Log Sources
# ------------------------------------------------------------------------------

variable "enable_alb_access_logs" {
  description = "Enable ALB access logs to S3"
  type        = bool
}

variable "enable_vpc_flow_logs" {
  description = "Enable VPC flow logs to CloudWatch"
  type        = bool
}

variable "enable_rds_log_exports" {
  description = "Enable RDS CloudWatch log exports"
  type        = bool
}

variable "enable_waf_logging" {
  description = "Enable WAF logging to Firehose"
  type        = bool
}

# ------------------------------------------------------------------------------
# Portal east-west inspection (#122)
# ------------------------------------------------------------------------------

variable "enable_portal_inspection" {
  description = "Insert an AWS Network Firewall east-west inspection boundary between the portal public (ALB) tier and the private services tier. Requires enable_log_aggregation = true."
  type        = bool
}

variable "firewall_log_retention_days" {
  description = "CloudWatch retention in days for portal Network Firewall FLOW / ALERT logs."
  type        = number
}

# ------------------------------------------------------------------------------
# Engine Provisioner
# ------------------------------------------------------------------------------

variable "engine_container_tag" {
  description = "Docker image tag for engine provisioner container"
  type        = string
  default     = "latest"
}

variable "dc_domain_name" {
  description = "Domain name for prebaked DC (e.g., internal.shifter)"
  type        = string
  default     = "internal.shifter"
}

# The DC Administrator password is intentionally not a Terraform variable.
# It lives in aws_secretsmanager_secret.dc_domain_password (created by
# the engine-provisioner module) with the value managed out-of-band, and
# is plumbed to the engine task via ECS `secrets = [...]` and to the
# portal Django container via the portal/ssm + ec2 modules and
# entrypoint.sh.

# Guacamole
# ------------------------------------------------------------------------------

variable "guacd_image_tag" {
  description = "Docker image tag for guacd"
  type        = string
}

variable "guacamole_client_image_tag" {
  description = "Docker image tag for guacamole-client"
  type        = string
}

variable "guacd_cpu" {
  description = "CPU units for guacd task"
  type        = number
}

variable "guacd_memory" {
  description = "Memory in MB for guacd task"
  type        = number
}

variable "guacamole_client_cpu" {
  description = "CPU units for guacamole-client task"
  type        = number
}

variable "guacamole_client_memory" {
  description = "Memory in MB for guacamole-client task"
  type        = number
}

variable "guacd_desired_count" {
  description = "Desired number of guacd tasks"
  type        = number
}

variable "guacamole_client_desired_count" {
  description = "Desired number of guacamole-client tasks"
  type        = number
}

variable "guacamole_db_instance_class" {
  description = "RDS instance class for Guacamole database"
  type        = string
}

variable "guacamole_db_allocated_storage" {
  description = "Allocated storage for Guacamole RDS in GB"
  type        = number
}

variable "guacamole_db_max_allocated_storage" {
  description = "Maximum storage for Guacamole RDS autoscaling in GB"
  type        = number
}

variable "guacamole_db_engine_version" {
  description = "PostgreSQL engine version for Guacamole"
  type        = string
}

variable "guacamole_db_multi_az" {
  description = "Enable Multi-AZ for Guacamole RDS"
  type        = bool
}

variable "guacamole_db_backup_retention_days" {
  description = "Backup retention days for Guacamole RDS"
  type        = number
}

variable "guacamole_db_deletion_protection" {
  description = "Enable deletion protection for Guacamole RDS"
  type        = bool
}

variable "guacamole_db_skip_final_snapshot" {
  description = "Skip final snapshot for Guacamole RDS"
  type        = bool
}

variable "guacamole_db_apply_immediately" {
  description = "Apply Guacamole RDS modifications during the deploy instead of queueing them for the maintenance window."
  type        = bool
}

variable "guacamole_enable_autoscaling" {
  description = "Enable autoscaling for Guacamole ECS services"
  type        = bool
}

variable "guacamole_autoscaling_min_capacity" {
  description = "Minimum capacity for Guacamole autoscaling"
  type        = number
}

variable "guacamole_autoscaling_max_capacity" {
  description = "Maximum capacity for Guacamole autoscaling"
  type        = number
}

variable "guacamole_autoscaling_cpu_target" {
  description = "CPU target for Guacamole autoscaling"
  type        = number
}

variable "guacamole_secrets_recovery_window_days" {
  description = "Recovery window for Guacamole secrets (0 for dev, 7+ for prod)"
  type        = number
}

variable "guacamole_enable_oidc" {
  description = "Enable OIDC/Cognito authentication for Guacamole"
  type        = bool
}

# ------------------------------------------------------------------------------
# Messaging (SNS/SQS)
# ------------------------------------------------------------------------------

variable "messaging_consumers" {
  description = "List of consumer names for SQS queues"
  type        = list(string)
}

variable "messaging_visibility_timeout_seconds" {
  description = "SQS visibility timeout in seconds"
  type        = number
}

variable "messaging_message_retention_seconds" {
  description = "SQS message retention period in seconds"
  type        = number
}

variable "messaging_enable_dlq" {
  description = "Enable dead letter queues for failed messages"
  type        = bool
}

variable "messaging_dlq_max_receive_count" {
  description = "Number of times a message can be received before moving to DLQ"
  type        = number
}

variable "messaging_dlq_message_retention_seconds" {
  description = "DLQ message retention period in seconds"
  type        = number
}

variable "messaging_enable_alarms" {
  description = "Enable CloudWatch alarms for queue monitoring"
  type        = bool
}

variable "messaging_alarm_queue_depth_threshold" {
  description = "Alarm threshold for approximate number of messages in queue"
  type        = number
}

variable "messaging_alarm_message_age_threshold" {
  description = "Alarm threshold for oldest message age in seconds"
  type        = number
}

variable "messaging_alarm_dlq_threshold" {
  description = "Alarm threshold for messages in DLQ"
  type        = number
}

variable "messaging_alarm_actions" {
  description = "List of ARNs to notify when alarm triggers (e.g., SNS topic ARNs)"
  type        = list(string)
}

# ------------------------------------------------------------------------------
# SES
# ------------------------------------------------------------------------------

variable "email_backend" {
  description = "Django email backend"
  type        = string
  default     = "django_ses.SESBackend"
}

variable "ctf_from_email" {
  description = "From address for CTF emails"
  type        = string
  default     = "ctf@example.com"
}

variable "ses_domain" {
  description = "Domain for SES email sending (e.g., example.com)"
  type        = string
}

# ------------------------------------------------------------------------------
# Alerting
# ------------------------------------------------------------------------------

variable "alarm_email" {
  description = "Email address for CloudWatch alarm notifications"
  type        = string
}

# ------------------------------------------------------------------------------
# Bedrock Logging
# ------------------------------------------------------------------------------

variable "enable_bedrock_logging" {
  description = "Enable Bedrock model invocation logging to CloudWatch"
  type        = bool
}

# ------------------------------------------------------------------------------
# CI Testing
# ------------------------------------------------------------------------------

variable "django_secret_key_ci" {
  description = "Django secret key for CI testing (extracted by quality.yml workflow, not used by Terraform)"
  type        = string
  default     = ""
}
