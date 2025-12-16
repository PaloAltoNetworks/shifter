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

variable "mcp_shifter_repository_name" {
  description = "Name for the mcp-shifter ECR repository"
  type        = string
  default     = "shifter-mcp-shifter"
}

variable "openwebui_repository_name" {
  description = "Name for the custom OpenWebUI ECR repository"
  type        = string
  default     = "shifter-openwebui"
}
