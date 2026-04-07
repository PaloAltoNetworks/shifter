# Pub/Sub for Shifter Range Events
#
# GCP equivalent of SNS + SQS. The provisioner publishes range status
# events (provisioning, ready, failed, destroyed) to the topic.
# The portal subscribes to receive status updates.

terraform {
  required_version = ">= 1.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }
}

resource "google_pubsub_topic" "range_events" {
  name    = "${var.name_prefix}-range-events"
  project = var.project_id

  labels = var.labels
}

# Portal subscription (pull-based — portal polls for updates)
resource "google_pubsub_subscription" "portal" {
  name    = "${var.name_prefix}-range-events-portal"
  topic   = google_pubsub_topic.range_events.id
  project = var.project_id

  ack_deadline_seconds = 30

  # Keep unacked messages for 7 days
  message_retention_duration = "604800s"

  # Auto-expire if no activity for 31 days
  expiration_policy {
    ttl = "2678400s"
  }

  labels = var.labels
}
