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

# ------------------------------------------------------------------------------
# EC2
# ------------------------------------------------------------------------------

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
  description = "Domain name for ACM certificate (e.g., shifter.keplerops.com)"
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

variable "victim_ami_id" {
  description = "AMI ID for victim EC2 instances"
  type        = string
}

variable "victim_instance_type" {
  description = "Instance type for victim EC2 instances"
  type        = string
  default     = "t3.micro"
}

variable "kali_ami_id" {
  description = "AMI ID for Kali EC2 instances (official AWS Marketplace Kali)"
  type        = string
}

variable "kali_instance_type" {
  description = "Instance type for Kali EC2 instances"
  type        = string
  default     = "t3.small"
}

variable "enable_provisioner_alarms" {
  description = "Enable CloudWatch alarms for provisioner Step Functions and Lambda"
  type        = bool
  default     = true
}

variable "provisioner_alarm_email" {
  description = "Email address for provisioner alarm notifications (leave empty to skip)"
  type        = string
  default     = ""
}

# ------------------------------------------------------------------------------
# Autoscaling
# ------------------------------------------------------------------------------

variable "enable_autoscaling" {
  description = "Enable Auto Scaling Group instead of single EC2 instance"
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

# ------------------------------------------------------------------------------
# Log Aggregation
# ------------------------------------------------------------------------------

variable "enable_log_aggregation" {
  description = "Enable log aggregation infrastructure (S3, SQS, Firehose)"
  type        = bool
}

variable "xdr_aws_account_id" {
  description = "AWS account ID for XDR cross-account access (empty if not configured)"
  type        = string
  default     = ""
}

variable "xdr_external_id" {
  description = "External ID for XDR cross-account role assumption"
  type        = string
  default     = ""
}

# ------------------------------------------------------------------------------
# CI Testing
# ------------------------------------------------------------------------------

variable "django_secret_key_ci" {
  description = "Django secret key for CI testing (extracted by quality.yml workflow, not used by Terraform)"
  type        = string
  default     = ""
}
