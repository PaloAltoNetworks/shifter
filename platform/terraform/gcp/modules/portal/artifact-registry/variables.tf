variable "project_id" {
  type = string
}

variable "artifact_registry_location" {
  type = string
}

variable "name_prefix" {
  type = string
}

variable "common_labels" {
  type = map(string)
}

variable "artifact_repositories" {
  type = set(string)
}

variable "environment" {
  type = string
}

variable "project_number" {
  type = number
}
