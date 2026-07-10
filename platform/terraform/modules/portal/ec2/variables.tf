variable "aws_region" {
  description = "AWS region"
  type        = string
}

variable "ec2_ami_id" {
  description = "AMI ID for portal EC2 instances (use standard AL2023, not ECS-optimized)"
  type        = string
}

variable "log_retention_days" {
  description = "CloudWatch log retention in days"
  type        = number
}

variable "name_prefix" {
  description = "Prefix for resource names"
  type        = string
}

variable "iam_name_prefix" {
  description = "Prefix for IAM role and instance profile names (defaults to name_prefix)"
  type        = string
  default     = null
}

variable "environment" {
  description = "Terraform environment slug (dev, prod, etc.) used to derive Django ENVIRONMENT for portal containers"
  type        = string
}

variable "vpc_id" {
  description = "VPC ID"
  type        = string
}

variable "subnet_id" {
  description = "Subnet ID for EC2 instance (private subnet)"
  type        = string
}

variable "alb_security_group_id" {
  description = "Security group ID of the ALB (for ingress rule)"
  type        = string
}

variable "instance_type" {
  description = "EC2 instance type"
  type        = string
}

variable "ecr_repository_arn" {
  description = "ARN of the ECR repository"
  type        = string
}

variable "ecr_repository_url" {
  description = "URL of the ECR repository"
  type        = string
}

variable "secret_arns" {
  description = "List of Secrets Manager secret ARNs the EC2 instance can read"
  type        = list(string)
}

variable "secrets_manager_kms_key_arn" {
  description = <<-EOT
    ARN of the portal Secrets Manager CMK. The EC2 role needs kms:Decrypt on
    this key to fetch values from any portal Secrets Manager secret encrypted
    with the CMK (e.g. the dc-domain password). Without it,
    `entrypoint.sh::fetch_runtime_secret` fails the get_secret_value call with
    `AccessDeniedException: Access to KMS is not allowed`. Required, no
    default. See issue #52.
  EOT
  type        = string
}

variable "app_port" {
  description = "Port the Django app listens on"
  type        = number
}

variable "root_volume_size" {
  description = "Size of root EBS volume in GB"
  type        = number
}

variable "s3_bucket_arn" {
  description = "ARN of the S3 bucket for user storage"
  type        = string
}

variable "tags" {
  description = "Tags to apply to resources"
  type        = map(string)
}

# ------------------------------------------------------------------------------
# ECS Variables (Pulumi Provisioner)
# ------------------------------------------------------------------------------

variable "ecs_cluster_arn" {
  description = "ARN of the ECS cluster for Pulumi provisioner"
  type        = string
}

variable "ecs_task_definition_arn" {
  description = "ARN of the ECS task definition for Pulumi provisioner (deprecated, use ecs_task_definition_family)"
  type        = string
  default     = ""
}

variable "ecs_task_definition_family" {
  description = "Family name of the ECS task definition for Pulumi provisioner (allows all revisions)"
  type        = string
}

variable "ecs_task_role_arn" {
  description = "ARN of the ECS task role (for iam:PassRole)"
  type        = string
}

variable "ecs_execution_role_arn" {
  description = "ARN of the ECS execution role (for iam:PassRole)"
  type        = string
}

# ------------------------------------------------------------------------------
# Autoscaling Variables - NO DEFAULTS
# ------------------------------------------------------------------------------

variable "enable_autoscaling" {
  description = "Enable Auto Scaling Group instead of single EC2 instance"
  type        = bool
}

variable "subnet_ids" {
  description = "List of subnet IDs for ASG multi-AZ deployment"
  type        = list(string)
}

variable "target_group_arn" {
  description = "ARN of the ALB target group for ASG attachment"
  type        = string
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

variable "asg_warm_pool_min_size" {
  description = "Minimum number of pre-initialized instances to keep in the ASG warm pool. Set 0 to disable the warm pool."
  type        = number
  default     = 0
}

variable "asg_warm_pool_state" {
  description = "Warm pool instance state. Valid values are Stopped, Running, or Hibernated."
  type        = string
  default     = "Stopped"

  validation {
    condition     = contains(["Stopped", "Running", "Hibernated"], var.asg_warm_pool_state)
    error_message = "asg_warm_pool_state must be one of: Stopped, Running, Hibernated."
  }
}

variable "redis_endpoint" {
  description = "Redis endpoint for Django Channels"
  type        = string
}

variable "scale_up_threshold" {
  description = "Average EC2 CPU percentage that fires the guardrail notification alarm (#940: CPU is no longer a scaling action, only a notification)."
  type        = number
}

# ------------------------------------------------------------------------------
# App-saturation autoscaling + observability (#940)
# ------------------------------------------------------------------------------

variable "alb_arn_suffix" {
  description = "ALB ARN suffix (app/<name>/<id>) for ALB CloudWatch dimensions and the ALBRequestCountPerTarget resource label."
  type        = string
}

variable "target_group_arn_suffix" {
  description = "Target group ARN suffix (targetgroup/<name>/<id>) for ALB CloudWatch dimensions and the ALBRequestCountPerTarget resource label."
  type        = string
}

variable "scale_target_requests_per_target" {
  description = "Target-tracking target value for ALBRequestCountPerTarget: requests per target per minute the ASG holds steady (primary request-path scale-out signal)."
  type        = number
  default     = 1000
}

variable "scale_target_response_time_seconds" {
  description = "Target-tracking target value for ALB TargetResponseTime (Average, seconds): the latency/queueing target the ASG holds steady."
  type        = number
  default     = 0.5
}

variable "scale_out_cooldown_seconds" {
  description = "Cooldown for the additive app-saturation simple scale-out policy."
  type        = number
  default     = 60
}

variable "worker_busy_ratio_scale_out_threshold" {
  description = "Hottest-worker WorkerBusyRatio (in-flight HTTP requests / soft concurrency) above which the additive app-saturation scale-out fires."
  type        = number
  default     = 0.8
}

variable "enable_portal_capacity_alarms" {
  description = "Create the portal capacity CloudWatch alarms and dashboard. PortalCapacity-namespace alarms also require the app emitter (PORTAL_CAPACITY_METRICS_ENABLED=true)."
  type        = bool
  default     = true
}

variable "portal_capacity_alarm_actions" {
  description = "SNS topic ARNs notified by the portal capacity / ALB observability alarms (typically the environment alerts topic)."
  type        = list(string)
  default     = []
}

variable "target_response_time_alarm_threshold_seconds" {
  description = "ALB p95 TargetResponseTime (seconds) above which the latency observability alarm notifies."
  type        = number
  default     = 1.0
}

variable "alb_target_5xx_alarm_threshold" {
  description = "ALB target 5xx count per period above which the 5xx observability alarm notifies."
  type        = number
  default     = 0
}

# ------------------------------------------------------------------------------
# Messaging Variables (SQS)
# ------------------------------------------------------------------------------

variable "sqs_queue_arns" {
  description = "List of SQS queue ARNs for message consumers"
  type        = list(string)
}

variable "sqs_queue_urls" {
  description = "Map of consumer name to SQS queue URL for message consumers"
  type        = map(string)
}

variable "sqs_kms_key_arn" {
  description = "ARN of the CMK encrypting the portal messaging SNS/SQS resources"
  type        = string
}

variable "s3_kms_key_arn" {
  description = "ARN of the CMK encrypting the portal user-storage S3 bucket (SSE-KMS). The instance role needs kms:GenerateDataKey/Decrypt on it (via the s3 service) to read and write challenge file attachments."
  type        = string
}

# ------------------------------------------------------------------------------
# Bootstrap Configuration (Parameter Store + Lifecycle Hook)
# ------------------------------------------------------------------------------

variable "ssm_parameter_store_prefix" {
  description = "Parameter Store prefix for deployment config (read by user_data)"
  type        = string
  default     = ""
}

variable "ses_domain_identity_arn" {
  description = "ARN of the SES domain identity for sending email (empty string to skip)"
  type        = string
  default     = ""
}

variable "enable_ses" {
  description = "Whether to create the SES send IAM policy. Use this instead of testing ses_domain_identity_arn to avoid count depending on unknown values."
  type        = bool
  default     = false
}

variable "lifecycle_hook_heartbeat_timeout" {
  description = "Heartbeat timeout for ASG lifecycle hook in seconds (max 7200)"
  type        = number
  default     = 600
}

variable "termination_drain_timeout" {
  description = <<-EOT
    Bounded drain window, in seconds, that a terminating instance is held in
    Terminating:Wait by the EC2_INSTANCE_TERMINATING lifecycle hook so the ALB
    can deregister the target and long-lived terminal/RDP/SSH WebSocket sessions
    can drain before SIGKILL (issue #931). Should be >= the target-group
    deregistration_delay and > the Docker stop timeout. AWS max is 7200.
  EOT
  type        = number
  default     = 180

  validation {
    condition     = var.termination_drain_timeout >= 30 && var.termination_drain_timeout <= 7200
    error_message = "termination_drain_timeout must be between 30 and 7200 seconds."
  }
}

variable "docker_stop_timeout" {
  description = <<-EOT
    Seconds Docker waits for a container to stop gracefully (SIGTERM) before
    SIGKILL during an in-place redeploy. Must exceed the Gunicorn graceful
    timeout (30s) so long-lived connections drain, and stay below
    termination_drain_timeout (issue #931).
  EOT
  type        = number
  default     = 35

  validation {
    condition     = var.docker_stop_timeout > 30 && var.docker_stop_timeout <= 600
    error_message = "docker_stop_timeout must be greater than 30 (the Gunicorn graceful timeout) and at most 600 seconds."
  }
}

variable "instance_refresh_min_healthy_percentage" {
  description = "Minimum percentage of healthy instances kept in service during an ASG instance refresh."
  type        = number
  default     = 50

  validation {
    condition     = var.instance_refresh_min_healthy_percentage >= 0 && var.instance_refresh_min_healthy_percentage <= 100
    error_message = "instance_refresh_min_healthy_percentage must be between 0 and 100."
  }
}

variable "worker_health_alarm_actions" {
  description = "SNS topic ARNs notified when worker lifecycle alarms (#953 unhealthy workers, #274 restart rate) fire; empty disables alarm notifications"
  type        = list(string)
  default     = []
}

variable "worker_restart_alarm_threshold" {
  description = "Aggregate WorkerRestarts count above which the restart-rate alarm notifies (#274)"
  type        = number
  default     = 3
}

variable "worker_restart_alarm_period_seconds" {
  description = "Evaluation period in seconds for the worker restart-rate alarm (#274)"
  type        = number
  default     = 300
}

variable "db_resource_id" {
  description = "RDS DbiResourceId (db-XXXX) used to scope the rds-db:connect grant for the portal runtime IAM database user (#159)."
  type        = string
}

variable "db_iam_runtime_user" {
  description = "PostgreSQL role the portal runtime connects as via RDS IAM authentication (created by mission_control migration 0041)."
  type        = string
  default     = "portal_runtime"
}

variable "permissions_boundary_arn" {
  description = "Permissions boundary ARN required on CI-created shifter-* roles"
  type        = string
}
