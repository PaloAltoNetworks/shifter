"""Add Scenario and ScenarioMetadata models.

Scenario stores staff-created custom scenario templates in the database.
ScenarioMetadata stores enabled/staff_only overlays for any scenario
(both YAML defaults and database customs).
"""

import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("cms", "0021_backfill_rangeinstance_requests"),
    ]

    operations = [
        migrations.CreateModel(
            name="Scenario",
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
                    "scenario_id",
                    models.SlugField(
                        help_text="URL-safe unique identifier (e.g., 'my-custom-lab')",
                        max_length=100,
                    ),
                ),
                (
                    "name",
                    models.CharField(help_text="Display name", max_length=200),
                ),
                (
                    "description",
                    models.TextField(help_text="User-facing description"),
                ),
                (
                    "definition",
                    models.JSONField(
                        help_text="Scenario structure: instances, subnets, ngfw flag",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "deleted_at",
                    models.DateTimeField(blank=True, null=True),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="created_scenarios",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "updated_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="updated_scenarios",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Scenario",
                "verbose_name_plural": "Scenarios",
                "ordering": ["name"],
            },
        ),
        migrations.AddConstraint(
            model_name="scenario",
            constraint=models.UniqueConstraint(
                condition=models.Q(("deleted_at__isnull", True)),
                fields=("scenario_id",),
                name="unique_active_scenario_id",
            ),
        ),
        migrations.CreateModel(
            name="ScenarioMetadata",
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
                    "scenario_id",
                    models.CharField(
                        help_text="Scenario ID (matches YAML or DB scenario id)",
                        max_length=100,
                        unique=True,
                    ),
                ),
                (
                    "enabled",
                    models.BooleanField(
                        default=True,
                        help_text="Whether this scenario is available for use",
                    ),
                ),
                (
                    "staff_only",
                    models.BooleanField(
                        default=False,
                        help_text="If True, only staff users can see/use this scenario",
                    ),
                ),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "updated_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Scenario Metadata",
                "verbose_name_plural": "Scenario Metadata",
                "ordering": ["scenario_id"],
            },
        ),
    ]
