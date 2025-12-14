# Provisioner Module Variables

variable "name_prefix" {
  description = "Prefix for resource names"
  type        = string
}

variable "environment" {
  description = "Environment name (prod, dev, etc.)"
  type        = string
  default     = "prod"
}

variable "tags" {
  description = "Tags to apply to all resources"
  type        = map(string)
  default     = {}
}

# Portal VPC (where Lambda runs)
variable "portal_vpc_id" {
  description = "VPC ID where Lambda functions will run"
  type        = string
}

variable "portal_subnet_ids" {
  description = "Private subnet IDs for Lambda functions"
  type        = list(string)
}

# Range VPC (where resources are created)
variable "range_vpc_id" {
  description = "VPC ID where range resources will be created"
  type        = string
}

variable "range_route_table_id" {
  description = "Route table ID for range subnets"
  type        = string
}

variable "range_cidr_prefix" {
  description = "CIDR prefix for range subnets (e.g., '10.1' for 10.1.0.0/16 VPC)"
  type        = string
}

variable "availability_zone" {
  description = "Availability zone for range subnets"
  type        = string
  default     = "us-east-2a"
}

# RDS Configuration
variable "db_host" {
  description = "RDS endpoint hostname"
  type        = string
}

variable "db_port" {
  description = "RDS port"
  type        = number
  default     = 5432
}

variable "db_name" {
  description = "Database name"
  type        = string
  default     = "shifter"
}

variable "db_resource_id" {
  description = "RDS resource ID for IAM DB authentication"
  type        = string
}

variable "rds_security_group_id" {
  description = "Security group ID for RDS access"
  type        = string
}

# Victim Configuration
variable "victim_ami_id" {
  description = "AMI ID for victim EC2 instances"
  type        = string
}

variable "victim_instance_type" {
  description = "Instance type for victim EC2 instances"
  type        = string
  default     = "t3.micro"
}

variable "victim_security_group_id" {
  description = "Security group ID for victim instances"
  type        = string
}

variable "agent_s3_bucket" {
  description = "S3 bucket containing XDR agent installers"
  type        = string
}

# Kali Configuration
variable "kali_ami_id" {
  description = "AMI ID for Kali EC2 instances (official AWS Marketplace Kali)"
  type        = string
}

variable "kali_instance_type" {
  description = "Instance type for Kali EC2 instances"
  type        = string
  default     = "t3.small"
}

variable "kali_security_group_id" {
  description = "Security group ID for Kali instances"
  type        = string
}

# Lambda Configuration
variable "lambda_timeout" {
  description = "Lambda function timeout in seconds"
  type        = number
  default     = 300
}

variable "lambda_memory" {
  description = "Lambda function memory in MB"
  type        = number
  default     = 256
}

# Chat Configuration
variable "chat_base_url" {
  description = "Base URL for the chat/MCP interface (e.g., https://chat.example.com)"
  type        = string
}

# Monitoring Configuration
variable "enable_alarms" {
  description = "Enable CloudWatch alarms for Step Functions and Lambda"
  type        = bool
  default     = true
}

variable "alarm_email" {
  description = "Email address for alarm notifications (leave empty to skip email subscription)"
  type        = string
  default     = ""
}
