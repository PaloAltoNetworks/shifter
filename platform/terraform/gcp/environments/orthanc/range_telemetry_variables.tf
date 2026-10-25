variable "range_telemetry" {
  description = "#2535 range audit telemetry from shifter.yaml settings.range_telemetry (rendered by `shifter-config render`). Omitted fields keep every control on; platform-core validates the values."
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
}
