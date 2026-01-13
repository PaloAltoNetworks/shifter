# Generated manually for EntityBase migration

import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def create_ngfw_catalog_types(apps, schema_editor):
    """Create InstanceType and AppType entries for NGFW."""
    InstanceType = apps.get_model("cms", "InstanceType")
    AppType = apps.get_model("cms", "AppType")

    InstanceType.objects.get_or_create(
        slug="panw-ngfw",
        defaults={
            "name": "PANW NGFW",
            "spec_class": "shared.schemas.range.InstanceSpec",
        },
    )

    AppType.objects.get_or_create(
        slug="panw-ngfw",
        defaults={
            "name": "Palo Alto Networks VM-Series",
            "spec_class": "shared.schemas.app.NGFWAppSpec",
        },
    )


def reverse_ngfw_catalog_types(apps, schema_editor):
    """Remove NGFW catalog entries."""
    InstanceType = apps.get_model("cms", "InstanceType")
    AppType = apps.get_model("cms", "AppType")

    InstanceType.objects.filter(slug="panw-ngfw").delete()
    AppType.objects.filter(slug="panw-ngfw").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("cms", "0015_ngfw_model"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # Create Request model (needed by Instance FK)
        migrations.CreateModel(
            name="Request",
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
                ("request_id", models.UUIDField(db_index=True, unique=True)),
                (
                    "request_type",
                    models.CharField(
                        choices=[("ngfw", "NGFW")], db_index=True, max_length=20
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="requests",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Request",
                "verbose_name_plural": "Requests",
                "ordering": ["-created_at"],
            },
        ),
        # Remove old Instance table and recreate with UUID PK
        migrations.DeleteModel(
            name="Instance",
        ),
        migrations.CreateModel(
            name="Instance",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        db_index=True,
                        default="pending",
                        max_length=20,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
                (
                    "name",
                    models.CharField(help_text="User-friendly name", max_length=100),
                ),
                (
                    "data",
                    models.JSONField(
                        default=dict,
                        help_text="Type-specific instance data (validated by spec_class)",
                    ),
                ),
                (
                    "instance_type",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="instance_configs",
                        to="cms.instancetype",
                    ),
                ),
                (
                    "request",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="instances",
                        to="cms.request",
                    ),
                ),
            ],
            options={
                "verbose_name": "Instance",
                "verbose_name_plural": "Instances",
                "ordering": ["-created_at"],
            },
        ),
        # Remove old App table and recreate with UUID PK
        migrations.DeleteModel(
            name="App",
        ),
        migrations.CreateModel(
            name="App",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        db_index=True,
                        default="pending",
                        max_length=20,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
                (
                    "name",
                    models.CharField(help_text="User-friendly name", max_length=100),
                ),
                (
                    "data",
                    models.JSONField(
                        default=dict,
                        help_text="Type-specific app data (validated by spec_class)",
                    ),
                ),
                (
                    "app_type",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="apps",
                        to="cms.apptype",
                    ),
                ),
                (
                    "instance",
                    models.ForeignKey(
                        blank=True,
                        help_text="Parent instance this app runs on",
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="apps",
                        to="cms.instance",
                    ),
                ),
            ],
            options={
                "verbose_name": "App",
                "verbose_name_plural": "Apps",
                "ordering": ["-created_at"],
            },
        ),
        # Create NGFW catalog entries
        migrations.RunPython(
            create_ngfw_catalog_types,
            reverse_ngfw_catalog_types,
        ),
    ]
