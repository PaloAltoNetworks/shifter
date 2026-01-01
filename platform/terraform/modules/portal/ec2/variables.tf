variable "aws_region" {
  description = "AWS region"
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

variable "redis_endpoint" {
  description = "Redis endpoint for Django Channels"
  type        = string
}

variable "scale_up_threshold" {
  description = "CPU percentage threshold to trigger scale up"
  type        = number
}

variable "scale_down_threshold" {
  description = "CPU percentage threshold to trigger scale down"
  type        = number
}
