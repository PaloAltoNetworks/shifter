"""Shared Django models."""

from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models


class WebSocketNotification(models.Model):
    """Durable per-recipient queue for browser WebSocket notifications."""

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="websocket_notifications",
    )
    event_id = models.UUIDField(default=uuid.uuid4)
    notification_type = models.CharField(max_length=128, db_index=True)
    topic = models.CharField(max_length=128, db_index=True)
    payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    delivered_at = models.DateTimeField(blank=True, null=True, db_index=True)
    expires_at = models.DateTimeField(db_index=True)

    class Meta:
        """Model metadata."""

        db_table = "shared_websocket_notification"
        ordering = ["created_at", "id"]
        indexes = [
            models.Index(fields=["recipient", "topic", "delivered_at"], name="wsn_rec_topic_delivery_idx"),
            models.Index(fields=["expires_at"], name="wsn_expires_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["recipient", "topic", "notification_type", "event_id"],
                name="uniq_wsn_rec_topic_type_event",
            ),
        ]

    def __str__(self) -> str:
        """Return a compact diagnostic representation."""
        return f"{self.notification_type}:{self.topic}:{self.recipient_id}"
