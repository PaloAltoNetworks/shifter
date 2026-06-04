# Generated for issue #679

import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="WebSocketNotification",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("event_id", models.UUIDField(default=uuid.uuid4)),
                ("notification_type", models.CharField(db_index=True, max_length=128)),
                ("topic", models.CharField(db_index=True, max_length=128)),
                ("payload", models.JSONField(default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("delivered_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("expires_at", models.DateTimeField(db_index=True)),
                (
                    "recipient",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="websocket_notifications",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "shared_websocket_notification",
                "ordering": ["created_at", "id"],
            },
        ),
        migrations.AddIndex(
            model_name="websocketnotification",
            index=models.Index(fields=["recipient", "topic", "delivered_at"], name="wsn_rec_topic_delivery_idx"),
        ),
        migrations.AddIndex(
            model_name="websocketnotification",
            index=models.Index(fields=["expires_at"], name="wsn_expires_idx"),
        ),
        migrations.AddConstraint(
            model_name="websocketnotification",
            constraint=models.UniqueConstraint(
                fields=("recipient", "topic", "notification_type", "event_id"),
                name="uniq_wsn_rec_topic_type_event",
            ),
        ),
    ]
