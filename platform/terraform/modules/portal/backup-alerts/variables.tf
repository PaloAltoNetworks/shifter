# SPDX-FileCopyrightText: 2026 Palo Alto Networks, Inc.
# SPDX-License-Identifier: MIT

# Backup-alerts module variables

variable "name_prefix" {
  description = "Prefix for resource names (e.g., prod-portal)"
  type        = string
}

variable "environment" {
  description = "Environment name (e.g., prod, dev, proof)"
  type        = string
}

variable "alarm_email" {
  description = "Email address subscribed to backup-failure notifications. Empty string disables the email subscription (the topic and event subscription are still created)."
  type        = string
  default     = ""
}

variable "db_instance_identifiers" {
  description = "RDS DB instance identifiers to watch for backup/availability/failure events. Empty list disables the event subscription."
  type        = list(string)
  default     = []
}

variable "tags" {
  description = "Common tags to apply to all resources"
  type        = map(string)
}
