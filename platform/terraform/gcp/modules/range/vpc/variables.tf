variable "project_id" {
  type = string
}

variable "region" {
  type = string
}

variable "name_prefix" {
  type = string
}

variable "gke_provisioner_pods_cidr" {
  type = string
}

variable "range_provisioner_ports" {
  type = list(number)
}

variable "operator_admin_cidrs" {
  type = list(string)
}

variable "range_egress_mode" {
  type = string
}

variable "range_egress_allowed_cidrs" {
  type = list(string)
}
