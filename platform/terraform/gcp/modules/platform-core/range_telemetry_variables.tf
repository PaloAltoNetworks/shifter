variable "range_telemetry" {
  description = <<-EOT
    #2535 range audit telemetry, rendered from shifter.yaml settings.range_telemetry by
    `shifter-config render`. Every control defaults on: VPC Flow Logs on range subnets,
    Cloud NAT logging on range egress, and Vertex AI DATA_READ/DATA_WRITE audit logs in
    this project. The provisioner receives the same policy through
    GCP_RANGE_TELEMETRY_POLICY_JSON. Disabling a control removes its records.
  EOT
  type = object({
    vpc_flow_logs = optional(object({
      enabled              = optional(bool, true)
      aggregation_interval = optional(string, "INTERVAL_5_SEC")
      flow_sampling        = optional(number, 0.5)
      metadata             = optional(string, "INCLUDE_ALL_METADATA")
    }), {})
    nat_logs = optional(object({
      enabled = optional(bool, true)
      filter  = optional(string, "ALL")
    }), {})
    vertex_data_access_logs = optional(object({
      enabled = optional(bool, true)
    }), {})
  })
  default  = {}
  nullable = false

  # Mirrors shared.gcp_range_telemetry for direct Terraform use.
  validation {
    condition = contains(
      ["INTERVAL_5_SEC", "INTERVAL_30_SEC", "INTERVAL_1_MIN", "INTERVAL_5_MIN", "INTERVAL_10_MIN", "INTERVAL_15_MIN"],
      var.range_telemetry.vpc_flow_logs.aggregation_interval,
    )
    error_message = "range_telemetry.vpc_flow_logs.aggregation_interval must be a Compute Engine flow-log interval."
  }

  validation {
    condition     = var.range_telemetry.vpc_flow_logs.flow_sampling > 0 && var.range_telemetry.vpc_flow_logs.flow_sampling <= 1
    error_message = "range_telemetry.vpc_flow_logs.flow_sampling must be greater than 0 and at most 1; disable the control instead of sampling at 0."
  }

  validation {
    condition     = contains(["INCLUDE_ALL_METADATA", "EXCLUDE_ALL_METADATA"], var.range_telemetry.vpc_flow_logs.metadata)
    error_message = "range_telemetry.vpc_flow_logs.metadata must be INCLUDE_ALL_METADATA or EXCLUDE_ALL_METADATA."
  }

  validation {
    condition     = contains(["ALL", "ERRORS_ONLY", "TRANSLATIONS_ONLY"], var.range_telemetry.nat_logs.filter)
    error_message = "range_telemetry.nat_logs.filter must be ALL, ERRORS_ONLY, or TRANSLATIONS_ONLY."
  }
}
