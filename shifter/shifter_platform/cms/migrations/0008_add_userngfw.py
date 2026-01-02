"""Add UserNGFW model to cms (moved from engine).

This is a state-only migration - no database changes.
The table already exists as mission_control_userngfw.
"""

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("cms", "0007_rangeinstance_agent_fk"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # State-only: tell Django cms app now owns UserNGFW
        # The table already exists from engine migrations
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name="UserNGFW",
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
                        (
                            "name",
                            models.CharField(help_text="User-friendly name", max_length=100),
                        ),
                        ("created_at", models.DateTimeField(auto_now_add=True)),
                        ("deleted_at", models.DateTimeField(blank=True, null=True)),
                        (
                            "status",
                            models.CharField(
                                choices=[
                                    ("not_provisioned", "Not Provisioned"),
                                    ("provisioning", "Provisioning"),
                                    ("ready", "Ready"),
                                    ("starting", "Starting"),
                                    ("active", "Active"),
                                    ("stopping", "Stopping"),
                                    ("stopped", "Stopped"),
                                    ("deprovisioning", "Deprovisioning"),
                                    ("failed", "Failed"),
                                ],
                                default="not_provisioned",
                                max_length=20,
                            ),
                        ),
                        ("instance_id", models.CharField(blank=True, max_length=32)),
                        ("mgmt_eni_id", models.CharField(blank=True, max_length=32)),
                        ("data_eni_id", models.CharField(blank=True, max_length=32)),
                        ("management_ip", models.GenericIPAddressField(blank=True, null=True)),
                        ("dataplane_ip", models.GenericIPAddressField(blank=True, null=True)),
                        ("gwlb_arn", models.CharField(blank=True, max_length=256)),
                        ("target_group_arn", models.CharField(blank=True, max_length=256)),
                        ("gwlb_service_name", models.CharField(blank=True, max_length=256)),
                        ("serial_number", models.CharField(blank=True, max_length=32)),
                        ("device_cert_status", models.CharField(blank=True, max_length=32)),
                        ("xdr_configured", models.BooleanField(default=False)),
                        ("provisioned_at", models.DateTimeField(blank=True, null=True)),
                        ("last_started_at", models.DateTimeField(blank=True, null=True)),
                        ("last_stopped_at", models.DateTimeField(blank=True, null=True)),
                        (
                            "user",
                            models.ForeignKey(
                                on_delete=models.deletion.CASCADE,
                                related_name="ngfws",
                                to=settings.AUTH_USER_MODEL,
                            ),
                        ),
                    ],
                    options={
                        "verbose_name": "User NGFW",
                        "verbose_name_plural": "User NGFWs",
                        "db_table": "mission_control_userngfw",
                        "ordering": ["-created_at"],
                    },
                ),
            ],
            database_operations=[],  # No DB changes - table already exists
        ),
    ]
