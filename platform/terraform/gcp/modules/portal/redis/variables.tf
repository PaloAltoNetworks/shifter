variable "project_id" {
  type = string
}

variable "region" {
  type = string
}

variable "name_prefix" {
  type = string
}

variable "environment" {
  type = string
}

variable "common_labels" {
  type = map(string)
}

variable "platform_network_id" {
  type = string
}

variable "redis_tier" {
  type = string
}

variable "redis_memory_size_gb" {
  type = number
}
