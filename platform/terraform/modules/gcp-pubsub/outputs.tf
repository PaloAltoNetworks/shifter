output "range_events_topic_name" {
  description = "Pub/Sub topic name for range events"
  value       = google_pubsub_topic.range_events.name
}

output "range_events_topic_id" {
  description = "Pub/Sub topic full ID (for provisioner config)"
  value       = google_pubsub_topic.range_events.id
}

output "portal_subscription_name" {
  description = "Portal subscription name"
  value       = google_pubsub_subscription.portal.name
}
