variable "bucket_name" {
  description = "Name of the S3 bucket (must be globally unique)"
  type        = string
}

variable "tags" {
  description = "Tags to apply to resources"
  type        = map(string)
  default     = {}
}

variable "cors_allowed_origins" {
  description = "Origins allowed to make CORS requests (for presigned URL uploads)"
  type        = list(string)
  default     = []
}

