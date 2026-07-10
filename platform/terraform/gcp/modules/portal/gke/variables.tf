variable "project_id" {
  type = string
}

variable "region" {
  type = string
}

variable "name_prefix" {
  type = string
}

variable "common_labels" {
  type = map(string)
}

variable "platform_network_id" {
  type = string
}

variable "gke_subnetwork_id" {
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

variable "gke_master_ipv4_cidr" {
  type = string
}

variable "gke_master_authorized_cidrs" {
  type = list(string)
}

variable "gke_release_channel" {
  type = string
}

variable "web_machine_type" {
  type = string
}

variable "worker_machine_type" {
  type = string
}

variable "provisioner_machine_type" {
  type = string
}

variable "web_node_count" {
  type = number
}

variable "worker_node_count" {
  type = number
}

variable "provisioner_node_count" {
  type = number
}

variable "node_service_account_email" {
  type = string
}
