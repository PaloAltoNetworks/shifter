variable "project_id" {
  description = "GCP project ID for the environment."
  type        = string
}

variable "required_services" {
  description = "GCP API services that must be enabled for the platform."
  type        = set(string)
}
