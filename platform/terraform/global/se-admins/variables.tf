variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-2"
}

variable "admins" {
  description = "Map of username to config for SE admin users"
  type = map(object({
    email = string
  }))
}
