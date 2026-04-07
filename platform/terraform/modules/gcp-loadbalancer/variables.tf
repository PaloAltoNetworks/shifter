variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "name_prefix" {
  description = "Prefix for resource names"
  type        = string
}

variable "domain_names" {
  description = "Domain names for the managed SSL certificate (e.g., ['shifter.example.com'])"
  type        = list(string)
}
