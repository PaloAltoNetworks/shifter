output "host" {
  description = "Redis instance hostname (private IP)"
  value       = google_redis_instance.this.host
}

output "port" {
  description = "Redis instance port"
  value       = google_redis_instance.this.port
}

output "auth_string" {
  description = "Redis AUTH string (empty if auth disabled)"
  value       = google_redis_instance.this.auth_string
  sensitive   = true
}

output "server_ca_cert" {
  description = "TLS CA certificate for in-transit encryption"
  value       = google_redis_instance.this.server_ca_certs[0].cert
  sensitive   = true
}
