# Add transactional outbox table for durable range/experiment event delivery (#476).

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("engine", "0022_range_provisioning_teardown_task_arns"),
    ]

    operations = [
        migrations.CreateModel(
            name="RangeEventOutbox",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("event_id", models.UUIDField(db_index=True, unique=True)),
                ("event_type", models.CharField(max_length=64)),
                ("payload", models.JSONField()),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("PENDING", "Pending"),
                            ("PUBLISHED", "Published"),
                            ("FAILED", "Failed"),
                            ("DLQ", "Dead Letter Queue"),
                        ],
                        db_index=True,
                        default="PENDING",
                        max_length=16,
                    ),
                ),
                ("attempts", models.PositiveIntegerField(default=0)),
                ("max_attempts", models.PositiveIntegerField(default=10)),
                ("next_attempt_at", models.DateTimeField(db_index=True)),
                ("last_error", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("published_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={
                "db_table": "engine_range_event_outbox",
                "indexes": [
                    models.Index(fields=["status", "next_attempt_at"], name="engine_rang_status_6f706a_idx"),
                ],
            },
        ),
    ]
