variable "region" {
  description = "AWS region"
  type        = string
  default     = "us-east-2"
}

variable "vpc_id" {
  description = "VPC ID for the runner"
  type        = string
}

variable "subnet_id" {
  description = "Subnet ID for the runner (should be public for GitHub connectivity)"
  type        = string
}

variable "instance_type" {
  description = "EC2 instance type"
  type        = string
  default     = "t3.large"
}

variable "github_org" {
  description = "GitHub organization or username"
  type        = string
  default     = "paloaltonetworks"
}

variable "github_repo" {
  description = "GitHub repository name"
  type        = string
  default     = "shifter"
}
