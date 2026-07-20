variable "project_id" {
  type = string
}

variable "region" {
  type = string
}

variable "environment" {
  type = string
}

variable "common_labels" {
  type = map(string)
}

variable "public_hostname" {
  type        = string
  default     = ""
  description = "Portal public hostname; when set, the assets bucket allows CORS from https://<hostname> for browser signed-URL uploads/downloads."
}
