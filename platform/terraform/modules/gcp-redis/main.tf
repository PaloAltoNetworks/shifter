# Memorystore for Redis — Django Channels and Session Cache
#
# GCP equivalent of portal/redis (ElastiCache). Used by the portal for:
# - Django Channels (WebSocket layer for real-time range status)
# - Session cache
#
# Uses the Private Services Access VPC peering created by the database module.
# Memorystore instances get private IPs on Google's managed network, reachable
# from the VPC via the same peering.
#
# Security:
# - Private IP only (no public access)
# - In-transit encryption (AUTH + TLS)
# - VPC-scoped access (no external networks)

terraform {
  required_version = ">= 1.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }
}

resource "google_redis_instance" "this" {
  name           = "${var.name_prefix}-redis"
  display_name   = "Shifter Redis (${var.name_prefix})"
  project        = var.project_id
  region         = var.region
  tier           = var.tier
  memory_size_gb = var.memory_size_gb
  redis_version  = var.redis_version

  # Network — uses existing Private Services Access peering
  authorized_network = var.network_id
  connect_mode       = "PRIVATE_SERVICE_ACCESS"

  # In-transit encryption
  transit_encryption_mode = "SERVER_AUTHENTICATION"

  # Auth (optional — adds a password requirement)
  auth_enabled = var.auth_enabled

  # Maintenance window (Monday 4 AM)
  maintenance_policy {
    weekly_maintenance_window {
      day = "MONDAY"
      start_time {
        hours   = 4
        minutes = 0
        seconds = 0
        nanos   = 0
      }
    }
  }

  # Redis configuration
  redis_configs = {
    maxmemory-policy = "allkeys-lru"
  }

  labels = var.labels
}
