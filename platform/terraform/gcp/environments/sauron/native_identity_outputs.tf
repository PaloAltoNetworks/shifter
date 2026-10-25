output "native_identity" {
  description = "Public native database identity metadata. No credential payloads."
  value       = module.platform_core.native_identity
}
