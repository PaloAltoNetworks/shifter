variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-2"
}

variable "portal_repository_name" {
  description = "Name for the portal ECR repository"
  type        = string
  default     = "shifter-portal"
}
