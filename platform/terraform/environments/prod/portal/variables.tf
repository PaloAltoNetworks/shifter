# Environment variables - NO DEFAULTS

# ------------------------------------------------------------------------------
# General
# ------------------------------------------------------------------------------

variable "environment" {
  description = "Environment name (e.g., prod, dev)"
  type        = string
}

# Renderer-owned backend selection (PLAT-2005). Supplied at deploy time via a
# rendered cloud_provider.auto.tfvars (shifter-config render-runtime), never a
# committed terraform.tfvars literal. No default: a missing tfvar must fail
# the plan loudly instead of silently synthesizing "aws".
variable "cloud_provider" {
  description = "Backend identity ('aws', 'gcp', ...) threaded to the portal ec2 and engine-provisioner module calls. Rendered from shifter.yaml's settings.backend; must not be hardcoded or defaulted here."
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

variable "db_ca_cert_identifier" {
  description = "RDS CA certificate identifier for portal and provisioner database TLS."
  type        = string
  default     = "rds-ca-rsa2048-g1"
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

variable "redis_apply_immediately" {
  description = "Apply ElastiCache Redis modifications during the deploy instead of queueing them for the maintenance window."
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

variable "terraform_state_bucket" {
  description = "S3 bucket hosting Terraform state for this deployment instance"
  type        = string
}

variable "terraform_state_region" {
  description = "AWS region for the Terraform state bucket"
  type        = string
  default     = "us-east-2"
}

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
  description = "Average EC2 CPU percentage that fires the guardrail notification alarm (#940: CPU is a notification, not a scaling action)."
  type        = number
}

# Portal app-saturation autoscaling + observability (#940). Scale-out tracks ALB
# request-path saturation instead of average EC2 CPU.
variable "scale_target_requests_per_target" {
  description = "ALBRequestCountPerTarget target-tracking value: requests per target per minute held steady (primary scale-out signal)."
  type        = number
  default     = 1000
}

variable "scale_target_response_time_seconds" {
  description = "ALB TargetResponseTime (Average, seconds) target-tracking value: the latency/queueing target held steady."
  type        = number
  default     = 0.5
}

variable "worker_busy_ratio_scale_out_threshold" {
  description = "Hottest-worker WorkerBusyRatio above which the additive app-saturation scale-out fires."
  type        = number
  default     = 0.8
}

variable "target_response_time_alarm_threshold_seconds" {
  description = "ALB p95 TargetResponseTime (seconds) above which the latency observability alarm notifies."
  type        = number
  default     = 1.0
}

variable "enable_portal_capacity_alarms" {
  description = "Create the portal capacity CloudWatch alarms and dashboard."
  type        = bool
  default     = true
}

variable "portal_capacity_metrics_enabled" {
  description = "Enable the per-worker Shifter/PortalCapacity metrics emitter (PORTAL_CAPACITY_METRICS_ENABLED)."
  type        = bool
  default     = false
}

variable "portal_worker_soft_concurrency" {
  description = "Busy-ratio denominator: soft concurrent in-flight HTTP request target per portal web worker (PORTAL_WORKER_SOFT_CONCURRENCY)."
  type        = number
  default     = 6
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

variable "portal_inspection_delete_protection" {
  description = "Enable delete protection on the portal inspection Network Firewall. Dev sets false to allow intentional teardown; prod keeps true. Mirrors the db_deletion_protection convention."
  type        = bool
}

# ------------------------------------------------------------------------------
# Engine Provisioner
# ------------------------------------------------------------------------------

variable "engine_container_tag" {
  description = "Docker image tag for engine provisioner container"
  type        = string
  default     = "latest"
}

variable "engine_container_image_digest" {
  description = "Immutable Docker image digest for engine provisioner container"
  type        = string
  default     = ""
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

variable "guacamole_db_ca_cert_identifier" {
  description = "RDS CA certificate identifier for Guacamole database TLS."
  type        = string
  default     = "rds-ca-rsa2048-g1"
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

# Portal runtime capacity tunables (#930). Forwarded to the portal/ssm module,
# which validates them; per-instance terminal cap = portal_web_workers *
# terminal_max_sessions. Set explicitly in terraform.tfvars so event capacity
# policy is visible in one place rather than hidden in the image defaults.
variable "portal_web_workers" {
  description = "Gunicorn/Uvicorn worker processes per portal instance (PORTAL_WEB_WORKERS), sized to instance vCPUs."
  type        = number
  default     = 4
}

variable "terminal_max_sessions" {
  description = "Active terminal SSH sessions per worker process (TERMINAL_MAX_SESSIONS)."
  type        = number
  default     = 200
}

variable "terminal_max_sessions_per_user" {
  description = "Active terminal SSH sessions per user, per worker process (TERMINAL_MAX_SESSIONS_PER_USER)."
  type        = number
  default     = 10
}

variable "terminal_idle_timeout_seconds" {
  description = "Idle terminal session timeout in seconds (TERMINAL_IDLE_TIMEOUT_SECONDS)."
  type        = number
  default     = 1800
}

variable "terminal_max_session_seconds" {
  description = "Hard ceiling on a terminal session lifetime in seconds (TERMINAL_MAX_SESSION_SECONDS)."
  type        = number
  default     = 28800
}

variable "terminal_read_poll_seconds" {
  description = "Idle terminal read-loop poll interval in seconds (TERMINAL_READ_POLL_SECONDS)."
  type        = number
  default     = 30
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

# ------------------------------------------------------------------------------
# Long-lived connection lifecycle (#931)
# ------------------------------------------------------------------------------
# Explicit, ordered timing for the portal's long-lived WebSocket / RDP / SSH
# workload. Prod uses full drain windows. Ordering: ws_ping(20s) < idle_timeout,
# and graceful(30s) < docker_stop < dereg <= termination_drain.

variable "alb_idle_timeout_seconds" {
  description = "ALB idle timeout (s) for long-lived WebSocket connections (#931)."
  type        = number
  default     = 300
}

variable "portal_deregistration_delay_seconds" {
  description = "Portal target-group deregistration delay (s) for connection drain (#931)."
  type        = number
  default     = 120
}

variable "guacamole_deregistration_delay_seconds" {
  description = "Guacamole target-group deregistration delay (s) for RDP/SSH drain (#931)."
  type        = number
  default     = 120
}

variable "termination_drain_timeout" {
  description = "ASG termination-drain hold (s) for in-flight session drain on refresh/scale-in (#931)."
  type        = number
  default     = 180
}

variable "docker_stop_timeout" {
  description = "Docker stop grace (s) on redeploy; must exceed the 30s Gunicorn graceful timeout (#931)."
  type        = number
  default     = 35
}

variable "instance_refresh_min_healthy_percentage" {
  description = "Minimum healthy percentage kept in service during an ASG instance refresh (#931)."
  type        = number
  default     = 50
}

variable "health_check_type" {
  description = "Portal ASG health-check type: ELB ties refresh readiness to ALB target health; EC2 is a non-ALB fallback (#1639)."
  type        = string
  default     = "ELB"
}

variable "health_check_grace_period" {
  description = "Seconds the portal ASG waits after launch before health checks count; env-owned so dev/proof can shorten the loop (#1639)."
  type        = number
  default     = 900
}

variable "instance_refresh_instance_warmup" {
  description = "Seconds an instance refresh waits for a replacement to warm up before counting it healthy; env-owned (#1639)."
  type        = number
  default     = 900
}

# --- AWS Polaris Bedrock agent credential profile (#1377) ---
# Off by default; populated (via the deploy-secrets tfvars mechanism) only in an
# environment that runs AWS Polaris ranges. Passed into the engine-provisioner
# module, which exposes them as the AWS_POLARIS_AGENT_* task env vars that
# config.load_aws_polaris_agent_config() consumes. An empty main inference-
# profile ARN keeps the feature disabled; an AWS polaris-vm range then fails
# closed rather than falling back to the removed IMDS path.
variable "aws_polaris_agent_region" {
  description = "AWS region for the per-range Polaris Bedrock agent STS + Bedrock calls (#1377). Empty disables the feature."
  type        = string
  default     = ""
}

variable "aws_polaris_agent_main_model_id" {
  description = "Bedrock main model id for the Polaris a14-kali agent (#1377)."
  type        = string
  default     = ""
}

variable "aws_polaris_agent_small_model_id" {
  description = "Bedrock small/fast model id for the Polaris a14-kali agent (#1377)."
  type        = string
  default     = ""
}

variable "aws_polaris_agent_main_inference_profile_arn" {
  description = "Approved Bedrock inference-profile ARN for the main model; the per-range Polaris agent enablement signal (#1377). Empty = disabled."
  type        = string
  default     = ""
}

variable "aws_polaris_agent_small_inference_profile_arn" {
  description = "Approved Bedrock inference-profile ARN for the small/fast model (#1377)."
  type        = string
  default     = ""
}

variable "aws_polaris_agent_main_backing_model_arns" {
  description = "Backing Bedrock foundation-model ARNs for the main inference profile (#1377)."
  type        = list(string)
  default     = []
}

variable "aws_polaris_agent_small_backing_model_arns" {
  description = "Backing Bedrock foundation-model ARNs for the small/fast inference profile (#1377)."
  type        = list(string)
  default     = []
}

variable "aws_polaris_agent_sts_session_duration_seconds" {
  description = "STS AssumeRole session duration (s) for the per-range Polaris agent credential (#1377)."
  type        = number
  default     = 900
}

variable "aws_polaris_agent_refresh_window_seconds" {
  description = "Refresh-before-expiry window (s) for the per-range Polaris agent credential (#1377)."
  type        = number
  default     = 300
}

variable "aces_package_bucket_arn" {
  description = "ARN of the S3 bucket holding object-backed ACES package archives (#1567). Grants the portal role read-only access; set it (with SHIFTER_ACES_PACKAGE_BUCKET on the app) to enable object-backed ACES packages. Empty disables the grant."
  type        = string
  default     = ""
}

variable "aces_package_prefix" {
  description = "Optional key prefix under the ACES package bucket the portal may read (least-privilege scoping)."
  type        = string
  default     = ""
}
