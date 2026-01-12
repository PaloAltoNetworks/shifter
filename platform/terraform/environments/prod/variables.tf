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

variable "pulumi_provisioner_repository_name" {
  description = "Name for the Pulumi provisioner ECR repository"
  type        = string
  default     = "shifter-prod-pulumi-provisioner"
}

variable "guacd_repository_name" {
  description = "Name for the guacd ECR repository"
  type        = string
  default     = "shifter-guacd"
}

variable "guacamole_client_repository_name" {
  description = "Name for the guacamole-client ECR repository"
  type        = string
  default     = "shifter-guacamole-client"
}
