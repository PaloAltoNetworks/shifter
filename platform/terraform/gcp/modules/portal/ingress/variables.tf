variable "project_id" {
  type = string
}

variable "name_prefix" {
  type = string
}

variable "common_labels" {
  type = map(string)
}

variable "normalized_public_hostname" {
  type = string
}

variable "create_dns_managed_zone" {
  type = bool
}

variable "dns_managed_zone_name" {
  type = string
}

variable "dns_zone_dns_name" {
  type = string
}

variable "dns_record_ttl" {
  type = number
}

variable "environment" {
  type = string
}
