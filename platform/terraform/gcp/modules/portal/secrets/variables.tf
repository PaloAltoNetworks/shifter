variable "project_id" {
  type = string
}

variable "name_prefix" {
  type = string
}

variable "common_labels" {
  type = map(string)
}

variable "runtime_secrets" {
  type = map(string)
}

variable "cloud_sql_private_ip" {
  type = string
}

variable "cloud_sql_platform_database_name" {
  type = string
}

variable "cloud_sql_platform_user_name" {
  type = string
}

variable "cloud_sql_db_password" {
  type      = string
  sensitive = true
}

variable "cloud_sql_guacamole_database_name" {
  type = string
}

variable "cloud_sql_guacamole_user_name" {
  type = string
}

variable "cloud_sql_guacamole_db_password" {
  type      = string
  sensitive = true
}

variable "redis_auth_string" {
  type      = string
  sensitive = true
}

variable "redis_server_ca_cert" {
  type = string
}
