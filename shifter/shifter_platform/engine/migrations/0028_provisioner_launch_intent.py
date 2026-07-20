import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("engine", "0027_aces_image_mapping")]

    operations = [
        migrations.AddField(
            model_name="instance",
            name="provisioner_operation",
            field=models.CharField(blank=True, default="", max_length=32),
        ),
        migrations.AddField(
            model_name="instance",
            name="provisioner_operation_id",
            field=models.UUIDField(blank=True, editable=False, null=True),
        ),
        migrations.AddField(
            model_name="range",
            name="provisioner_operation",
            field=models.CharField(blank=True, default="", max_length=32),
        ),
        migrations.AddField(
            model_name="range",
            name="provisioner_operation_id",
            field=models.UUIDField(blank=True, editable=False, null=True),
        ),
        migrations.CreateModel(
            name="ProvisionerLaunchIntent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("intent_id", models.UUIDField(db_index=True, default=uuid.uuid4, unique=True)),
                ("operation_id", models.UUIDField(editable=False, unique=True)),
                ("idempotency_key", models.CharField(max_length=255)),
                ("payload", models.JSONField()),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("PENDING", "Pending"),
                            ("RUNNING", "Running"),
                            ("SUCCEEDED", "Succeeded"),
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
                ("last_error", models.CharField(blank=True, default="", max_length=128)),
                ("task_ref", models.CharField(blank=True, default="", max_length=512)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("launched_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={
                "db_table": "engine_provisioner_launch_intent",
                "indexes": [models.Index(fields=["status", "next_attempt_at"], name="engine_prov_status_due_idx")],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("idempotency_key",),
                        name="unique_provisioner_launch_operation",
                    )
                ],
            },
        ),
    ]
