"""Initial migration for engine app.

This migration moves Range and UserNGFW models from mission_control to engine
using SeparateDatabaseAndState. The database tables remain unchanged
(mission_control_range, mission_control_userngfw).
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("cms", "0001_initial"),
        # Depend on the last mission_control migration that touched these models
        ("mission_control", "0034_cleanup_moved_models"),
    ]

    operations = [
        # Use SeparateDatabaseAndState: state_operations update Django's model registry
        # but don't touch the database (tables already exist from mission_control migrations)
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
                        ("name", models.CharField(max_length=255)),
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
                                on_delete=django.db.models.deletion.CASCADE,
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
                migrations.CreateModel(
                    name="Range",
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
                            "gwlb_endpoint_id",
                            models.CharField(
                                blank=True,
                                default="",
                                help_text="GWLB endpoint ID for this range's NGFW",
                                max_length=32,
                            ),
                        ),
                        (
                            "status",
                            models.CharField(
                                choices=[
                                    ("pending", "Pending"),
                                    ("provisioning", "Provisioning"),
                                    ("ready", "Ready"),
                                    ("paused", "Paused"),
                                    ("resuming", "Resuming"),
                                    ("destroying", "Destroying"),
                                    ("destroyed", "Destroyed"),
                                    ("failed", "Failed"),
                                ],
                                db_index=True,
                                default="pending",
                                max_length=20,
                            ),
                        ),
                        (
                            "subnet_id",
                            models.CharField(
                                blank=True,
                                default="",
                                help_text="AWS subnet ID (e.g., subnet-abc123)",
                                max_length=50,
                            ),
                        ),
                        (
                            "subnet_cidr",
                            models.CharField(
                                blank=True,
                                default="",
                                help_text="Subnet CIDR (e.g., 10.1.5.0/24)",
                                max_length=18,
                            ),
                        ),
                        (
                            "subnet_index",
                            models.PositiveIntegerField(
                                blank=True,
                                help_text="Unique index for CIDR allocation",
                                null=True,
                            ),
                        ),
                        ("victim_ip", models.GenericIPAddressField(blank=True, null=True)),
                        (
                            "victim_instance_id",
                            models.CharField(
                                blank=True,
                                default="",
                                help_text="EC2 instance ID (e.g., i-abc123)",
                                max_length=50,
                            ),
                        ),
                        ("kali_ip", models.GenericIPAddressField(blank=True, null=True)),
                        (
                            "kali_instance_id",
                            models.CharField(
                                blank=True,
                                default="",
                                help_text="Kali EC2 instance ID (e.g., i-abc123)",
                                max_length=50,
                            ),
                        ),
                        (
                            "kali_ssh_key_secret_arn",
                            models.CharField(
                                blank=True,
                                default="",
                                help_text="Secrets Manager ARN for Kali SSH private key",
                                max_length=500,
                            ),
                        ),
                        (
                            "victim_ssh_key_secret_arn",
                            models.CharField(
                                blank=True,
                                default="",
                                help_text="Secrets Manager ARN for Victim SSH private key",
                                max_length=500,
                            ),
                        ),
                        ("chat_url", models.URLField(blank=True, default="", max_length=500)),
                        (
                            "step_function_execution_arn",
                            models.CharField(
                                blank=True,
                                default="",
                                help_text="Step Functions execution ARN",
                                max_length=500,
                            ),
                        ),
                        (
                            "instance_config",
                            models.JSONField(
                                blank=True,
                                help_text="JSON array of instance configurations for Shifter Engine",
                                null=True,
                            ),
                        ),
                        (
                            "provisioned_instances",
                            models.JSONField(
                                blank=True,
                                help_text="JSON array of provisioned instance details from Pulumi",
                                null=True,
                            ),
                        ),
                        (
                            "pulumi_stack",
                            models.CharField(
                                blank=True,
                                default="",
                                help_text="Pulumi stack name for this range",
                                max_length=255,
                            ),
                        ),
                        (
                            "provisioner_version",
                            models.CharField(
                                default="v1",
                                help_text="Provisioner version: v1=Lambda, v2=Pulumi",
                                max_length=10,
                            ),
                        ),
                        ("error_message", models.TextField(blank=True, default="")),
                        ("created_at", models.DateTimeField(auto_now_add=True)),
                        ("updated_at", models.DateTimeField(auto_now=True)),
                        ("ready_at", models.DateTimeField(blank=True, null=True)),
                        ("paused_at", models.DateTimeField(blank=True, null=True)),
                        ("destroyed_at", models.DateTimeField(blank=True, null=True)),
                        (
                            "agent",
                            models.ForeignKey(
                                blank=True,
                                help_text="Agent for victim instances",
                                null=True,
                                on_delete=django.db.models.deletion.SET_NULL,
                                related_name="ranges",
                                to="cms.agentconfig",
                            ),
                        ),
                        (
                            "dc_agent",
                            models.ForeignKey(
                                blank=True,
                                help_text="Agent for DC instances (Windows only, required for AD scenarios)",
                                null=True,
                                on_delete=django.db.models.deletion.SET_NULL,
                                related_name="dc_ranges",
                                to="cms.agentconfig",
                            ),
                        ),
                        (
                            "ngfw",
                            models.ForeignKey(
                                blank=True,
                                help_text="Persistent NGFW instance for this range",
                                null=True,
                                on_delete=django.db.models.deletion.SET_NULL,
                                related_name="ranges",
                                to="engine.userngfw",
                            ),
                        ),
                        (
                            "user",
                            models.ForeignKey(
                                on_delete=django.db.models.deletion.CASCADE,
                                related_name="ranges",
                                to=settings.AUTH_USER_MODEL,
                            ),
                        ),
                    ],
                    options={
                        "db_table": "mission_control_range",
                        "ordering": ["-created_at"],
                    },
                ),
            ],
            database_operations=[],
        ),
    ]
