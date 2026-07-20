output "identity_platform_api_key" {
  description = "Identity Platform web API key for the project."
  value       = google_identity_platform_config.platform.client[0].api_key
  sensitive   = true
}
