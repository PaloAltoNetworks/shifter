# Messaging module - Pub/Sub topic/subscriptions for platform lifecycle events.
#
# Creates:
# - Shared Pub/Sub topic for platform events (provisioner publishes here)
# - Per-worker Pub/Sub subscriptions (fan-out, with retry policy)
# - Dead-letter topic + retention subscription (enable_dlq=true)
# - IAM bindings for Pub/Sub service agent to dead-letter (enable_dlq=true)
# - Cloud Monitoring alert policies for queue depth, message age,
#   and dead-letter message count (enable_alarms=true)

data "google_project" "project" {
  project_id = var.project_id
}

locals {
  # Pub/Sub service agent that GCP requires to move messages to the dead-letter topic.
  pubsub_sa = "serviceAccount:service-${data.google_project.project.number}@gcp-sa-pubsub.iam.gserviceaccount.com"
}

# ------------------------------------------------------------------------------
# Source Topic
# ------------------------------------------------------------------------------

resource "google_pubsub_topic" "platform_events" {
  name    = "${var.name_prefix}-events"
  project = var.project_id
  labels  = var.common_labels
}

# ------------------------------------------------------------------------------
# Dead-Letter Topic (enable_dlq)
# ------------------------------------------------------------------------------

resource "google_pubsub_topic" "dead_letter" {
  count = var.enable_dlq ? 1 : 0

  name    = "${var.name_prefix}-events-dead-letter"
  project = var.project_id
  labels  = merge(var.common_labels, { role = "dead-letter" })
}

# ------------------------------------------------------------------------------
# Dead-Letter Retention Subscription
# Holds dead-lettered messages for operator inspection and replay.
# (Parity: AWS DLQ retains messages for dlq_message_retention_seconds.)
# ------------------------------------------------------------------------------

resource "google_pubsub_subscription" "dead_letter" {
  count = var.enable_dlq ? 1 : 0

  name                       = "${var.name_prefix}-events-dead-letter"
  project                    = var.project_id
  topic                      = google_pubsub_topic.dead_letter[0].name
  ack_deadline_seconds       = 600
  message_retention_duration = var.dlq_retention
  labels                     = merge(var.common_labels, { role = "dead-letter" })
}

# ------------------------------------------------------------------------------
# Per-Worker Source Subscriptions (with retry policy and optional dead-letter)
# ------------------------------------------------------------------------------

resource "google_pubsub_subscription" "platform_events" {
  for_each = var.platform_event_subscriptions

  name                       = "${var.name_prefix}-${each.key}"
  project                    = var.project_id
  topic                      = google_pubsub_topic.platform_events.name
  ack_deadline_seconds       = 20
  message_retention_duration = "604800s"
  labels                     = merge(var.common_labels, { worker = each.key })

  dynamic "dead_letter_policy" {
    for_each = var.enable_dlq ? [1] : []
    content {
      dead_letter_topic     = google_pubsub_topic.dead_letter[0].id
      max_delivery_attempts = var.max_delivery_attempts
    }
  }

  retry_policy {
    minimum_backoff = var.retry_min_backoff
    maximum_backoff = var.retry_max_backoff
  }
}

# ------------------------------------------------------------------------------
# IAM: Pub/Sub service agent must be able to publish to the dead-letter topic
# and to acknowledge messages from each source subscription.
# GCP requires these bindings or dead-lettering silently fails.
# ------------------------------------------------------------------------------

resource "google_pubsub_topic_iam_member" "pubsub_sa_dl_publisher" {
  count = var.enable_dlq ? 1 : 0

  project = var.project_id
  topic   = google_pubsub_topic.dead_letter[0].name
  role    = "roles/pubsub.publisher"
  member  = local.pubsub_sa
}

resource "google_pubsub_subscription_iam_member" "pubsub_sa_source_subscriber" {
  for_each = var.enable_dlq ? var.platform_event_subscriptions : toset([])

  project      = var.project_id
  subscription = google_pubsub_subscription.platform_events[each.key].name
  role         = "roles/pubsub.subscriber"
  member       = local.pubsub_sa
}

# ------------------------------------------------------------------------------
# Cloud Monitoring Alerts - Queue Depth
# (Parity: AWS CloudWatch ApproximateNumberOfMessagesVisible per consumer queue)
# ------------------------------------------------------------------------------

resource "google_monitoring_alert_policy" "queue_depth" {
  for_each = var.enable_alarms ? var.platform_event_subscriptions : toset([])

  project      = var.project_id
  display_name = "${var.name_prefix}-${each.key}-queue-depth"
  combiner     = "OR"

  conditions {
    display_name = "Undelivered messages in ${each.key} subscription exceed threshold"

    condition_threshold {
      filter = join(" AND ", [
        "resource.type=\"pubsub_subscription\"",
        "resource.labels.subscription_id=\"${google_pubsub_subscription.platform_events[each.key].name}\"",
        "metric.type=\"pubsub.googleapis.com/subscription/num_undelivered_messages\"",
      ])
      duration        = "60s"
      comparison      = "COMPARISON_GT"
      threshold_value = var.alarm_queue_depth_threshold

      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_MEAN"
      }
    }
  }

  notification_channels = var.notification_channels

  alert_strategy {
    auto_close = "604800s"
  }
}

# ------------------------------------------------------------------------------
# Cloud Monitoring Alerts - Message Age
# (Parity: AWS CloudWatch ApproximateAgeOfOldestMessage per consumer queue)
# ------------------------------------------------------------------------------

resource "google_monitoring_alert_policy" "message_age" {
  for_each = var.enable_alarms ? var.platform_event_subscriptions : toset([])

  project      = var.project_id
  display_name = "${var.name_prefix}-${each.key}-message-age"
  combiner     = "OR"

  conditions {
    display_name = "Oldest unacked message in ${each.key} subscription is too old"

    condition_threshold {
      filter = join(" AND ", [
        "resource.type=\"pubsub_subscription\"",
        "resource.labels.subscription_id=\"${google_pubsub_subscription.platform_events[each.key].name}\"",
        "metric.type=\"pubsub.googleapis.com/subscription/oldest_unacked_message_age\"",
      ])
      duration        = "60s"
      comparison      = "COMPARISON_GT"
      threshold_value = var.alarm_message_age_threshold

      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_MAX"
      }
    }
  }

  notification_channels = var.notification_channels

  alert_strategy {
    auto_close = "604800s"
  }
}

# ------------------------------------------------------------------------------
# Cloud Monitoring Alerts - Dead-Letter Messages
# (Parity: AWS CloudWatch ApproximateNumberOfMessagesVisible on DLQ)
# ------------------------------------------------------------------------------

resource "google_monitoring_alert_policy" "dlq_messages" {
  count = var.enable_alarms && var.enable_dlq ? 1 : 0

  project      = var.project_id
  display_name = "${var.name_prefix}-events-dlq-messages"
  combiner     = "OR"

  conditions {
    display_name = "Messages in dead-letter subscription"

    condition_threshold {
      filter = join(" AND ", [
        "resource.type=\"pubsub_subscription\"",
        "resource.labels.subscription_id=\"${google_pubsub_subscription.dead_letter[0].name}\"",
        "metric.type=\"pubsub.googleapis.com/subscription/num_undelivered_messages\"",
      ])
      duration        = "60s"
      comparison      = "COMPARISON_GE"
      threshold_value = var.alarm_dlq_threshold

      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_SUM"
      }
    }
  }

  notification_channels = var.notification_channels

  alert_strategy {
    auto_close = "604800s"
  }
}
