output "control_plane_cache" {
  description = "Control-plane Redis connection metadata."
  value = {
    host        = google_redis_instance.platform.host
    port        = google_redis_instance.platform.port
    tls_enabled = google_redis_instance.platform.transit_encryption_mode != "DISABLED"
  }
}

output "auth_string" {
  description = "Redis AUTH token."
  value       = google_redis_instance.platform.auth_string
  sensitive   = true
}

output "server_ca_cert" {
  description = "Memorystore server CA certificate PEM."
  value       = google_redis_instance.platform.server_ca_certs[0].cert
}
