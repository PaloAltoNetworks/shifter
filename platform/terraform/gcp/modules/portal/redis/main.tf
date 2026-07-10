resource "google_redis_instance" "platform" {
  name               = "${var.name_prefix}-redis"
  project            = var.project_id
  region             = var.region
  tier               = var.redis_tier
  memory_size_gb     = var.redis_memory_size_gb
  authorized_network = var.platform_network_id
  connect_mode       = "PRIVATE_SERVICE_ACCESS"
  display_name       = "Shifter ${var.environment} Redis"
  labels             = var.common_labels

  auth_enabled            = true
  transit_encryption_mode = "SERVER_AUTHENTICATION"
}
