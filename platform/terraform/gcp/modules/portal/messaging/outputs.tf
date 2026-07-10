output "platform_events_topic_id" {
  description = "Shared Pub/Sub topic for platform lifecycle events."
  value       = google_pubsub_topic.platform_events.id
}

output "platform_event_subscriptions" {
  description = "Pub/Sub subscriptions keyed by worker role."
  value = {
    for name, subscription in google_pubsub_subscription.platform_events :
    name => subscription.id
  }
}

output "dead_letter_topic_id" {
  description = "Dead-letter Pub/Sub topic ID. Null when enable_dlq is false."
  value       = var.enable_dlq ? google_pubsub_topic.dead_letter[0].id : null
}

output "dead_letter_subscription_id" {
  description = "Dead-letter retention subscription ID. Null when enable_dlq is false."
  value       = var.enable_dlq ? google_pubsub_subscription.dead_letter[0].id : null
}
