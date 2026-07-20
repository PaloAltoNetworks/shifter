from __future__ import annotations

import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("mission_control", "0038_grant_range_config_to_provisioner"),
    ]

    operations = [
        migrations.CreateModel(
            name="GuacamoleBootstrapRequest",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("user_id", models.PositiveBigIntegerField(db_index=True)),
                (
                    "protocol",
                    models.CharField(
                        choices=[
                            ("rdp", "RDP"),
                            ("range_ssh", "Range SSH"),
                            ("ngfw_ssh", "NGFW SSH"),
                        ],
                        max_length=16,
                    ),
                ),
                ("target_id", models.CharField(max_length=200)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("running", "Running"),
                            ("succeeded", "Succeeded"),
                            ("failed", "Failed"),
                        ],
                        db_index=True,
                        default="pending",
                        max_length=16,
                    ),
                ),
                ("result_url", models.TextField(blank=True)),
                ("error_message", models.CharField(blank=True, max_length=500)),
                ("error_status_code", models.PositiveSmallIntegerField(default=500)),
                ("duration_ms", models.PositiveIntegerField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("expires_at", models.DateTimeField(db_index=True)),
            ],
            options={
                "ordering": ("-created_at",),
                "indexes": [
                    models.Index(fields=("user_id", "created_at"), name="mc_guac_boot_user_idx"),
                    models.Index(fields=("status", "expires_at"), name="mc_guac_boot_state_idx"),
                ],
            },
        ),
    ]
