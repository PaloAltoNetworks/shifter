variable "project_id" {
  type = string
}

variable "region" {
  type = string
}

variable "name_prefix" {
  type = string
}

variable "gke_subnet_cidr" {
  type = string
}

variable "gke_pods_cidr" {
  type = string
}

variable "gke_services_cidr" {
  type = string
}

variable "gke_provisioner_pods_cidr" {
  type = string
}

variable "gke_pods_secondary_range_name" {
  type = string
}

variable "gke_services_secondary_range_name" {
  type = string
}

variable "gke_provisioner_pods_secondary_range_name" {
  type = string
}

variable "private_service_range_prefix_length" {
  type = number
}

variable "operator_admin_cidrs" {
  type = list(string)
}
