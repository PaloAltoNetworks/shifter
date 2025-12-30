# ------------------------------------------------------------------------------
# Core Variables
# ------------------------------------------------------------------------------

variable "name_prefix" {
  description = "Prefix for resource names"
  type        = string
}

variable "environment" {
  description = "Environment name (dev, prod)"
  type        = string
}

variable "tags" {
  description = "Tags to apply to all resources"
  type        = map(string)
  default     = {}
}

variable "log_retention_days" {
  description = "CloudWatch log retention in days"
  type        = number
  default     = 30
}

# ------------------------------------------------------------------------------
# ECS Configuration
# ------------------------------------------------------------------------------

variable "ecr_repository_url" {
  description = "URL of the ECR repository for the Pulumi provisioner image"
  type        = string
}

variable "container_image_tag" {
  description = "Docker image tag to deploy"
  type        = string
  default     = "latest"
}

variable "task_cpu" {
  description = "CPU units for the ECS task (1024 = 1 vCPU)"
  type        = number
  default     = 1024
}

variable "task_memory" {
  description = "Memory in MB for the ECS task"
  type        = number
  default     = 2048
}

# ------------------------------------------------------------------------------
# Networking
# ------------------------------------------------------------------------------

variable "vpc_id" {
  description = "ID of the Portal VPC where ECS tasks run"
  type        = string
}

variable "private_subnet_ids" {
  description = "List of private subnet IDs for ECS tasks"
  type        = list(string)
}

# ------------------------------------------------------------------------------
# Database (RDS IAM Auth)
# ------------------------------------------------------------------------------

variable "db_host" {
  description = "RDS database hostname"
  type        = string
}

variable "db_port" {
  description = "RDS database port"
  type        = number
  default     = 5432
}

variable "db_name" {
  description = "RDS database name"
  type        = string
}

variable "db_resource_id" {
  description = "RDS resource ID for IAM authentication"
  type        = string
}

variable "rds_security_group_id" {
  description = "Security group ID of the RDS instance"
  type        = string
}

# ------------------------------------------------------------------------------
# Pulumi State Backend
# ------------------------------------------------------------------------------

variable "pulumi_state_bucket" {
  description = "S3 bucket name for Pulumi state"
  type        = string
}

variable "pulumi_state_bucket_arn" {
  description = "S3 bucket ARN for Pulumi state"
  type        = string
}

variable "pulumi_locks_table" {
  description = "DynamoDB table name for Pulumi locking"
  type        = string
}

variable "pulumi_locks_table_arn" {
  description = "DynamoDB table ARN for Pulumi locking"
  type        = string
}

variable "pulumi_secrets_kms_key_arn" {
  description = "ARN of the KMS key for Pulumi secrets encryption"
  type        = string
}

variable "pulumi_secrets_kms_key_alias" {
  description = "Alias of the KMS key for Pulumi secrets encryption (e.g., alias/dev-range-pulumi-secrets)"
  type        = string
}

# ------------------------------------------------------------------------------
# Range VPC Configuration
# ------------------------------------------------------------------------------

variable "range_vpc_id" {
  description = "ID of the Range VPC where instances are provisioned"
  type        = string
}

variable "range_vpc_cidr" {
  description = "CIDR block of the Range VPC"
  type        = string
}

variable "range_route_table_id" {
  description = "Route table ID for range subnets"
  type        = string
}

variable "range_availability_zone" {
  description = "Availability zone for range subnets (e.g., us-east-2a)"
  type        = string
}

variable "victim_security_group_id" {
  description = "Security group ID for victim instances"
  type        = string
}

variable "kali_security_group_id" {
  description = "Security group ID for Kali instances"
  type        = string
}

variable "dc_security_group_id" {
  description = "Security group ID for Domain Controller instances"
  type        = string
  default     = ""
}

variable "range_instance_profile_arn" {
  description = "IAM instance profile ARN for range instances"
  type        = string
}

variable "range_instance_profile_name" {
  description = "IAM instance profile name for range instances"
  type        = string
}

variable "range_instance_role_arn" {
  description = "IAM role ARN for range instances (required for iam:PassRole)"
  type        = string
}

# ------------------------------------------------------------------------------
# AMI IDs
# ------------------------------------------------------------------------------

variable "kali_ami_id" {
  description = "AMI ID for Kali Linux instances"
  type        = string
}

variable "victim_ami_id" {
  description = "AMI ID for Linux victim instances"
  type        = string
}

variable "windows_ami_id" {
  description = "AMI ID for Windows victim instances"
  type        = string
  default     = ""
}

variable "dc_ami_id" {
  description = "AMI ID for Domain Controller instances (prebaked with AD DS promoted)"
  type        = string
  default     = ""
}

variable "dc_domain_name" {
  description = "Domain name for prebaked DC (e.g., internal.shifter)"
  type        = string
  default     = "internal.shifter"
}

variable "dc_domain_password" {
  description = "Domain admin password for prebaked DC"
  type        = string
  sensitive   = true
  default     = ""
}

# ------------------------------------------------------------------------------
# Instance Types
# ------------------------------------------------------------------------------

variable "kali_instance_type" {
  description = "EC2 instance type for Kali attacker instances"
  type        = string
}

variable "victim_instance_type" {
  description = "EC2 instance type for victim instances"
  type        = string
}

# ------------------------------------------------------------------------------
# S3 Agent Bucket
# ------------------------------------------------------------------------------

variable "agent_s3_bucket" {
  description = "S3 bucket name for XDR agent installers"
  type        = string
}

variable "agent_s3_bucket_arn" {
  description = "S3 bucket ARN for XDR agent installers"
  type        = string
}

# ------------------------------------------------------------------------------
# Alarms Configuration
# ------------------------------------------------------------------------------

variable "enable_alarms" {
  description = "Enable CloudWatch alarms for range launch failures"
  type        = bool
  default     = false
}

variable "alarm_email" {
  description = "Email address for alarm notifications (leave empty to skip)"
  type        = string
  default     = ""
}
