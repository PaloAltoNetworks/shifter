# Generated for PLAT-202 / issue #2140.

import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("ctf", "0054_scheduler_claim_fence_intent_expired"),
    ]

    operations = [
        migrations.CreateModel(
            name="CTFCohort",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        help_text="Unique identifier for cross-system correlation",
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(
                        auto_now_add=True,
                        db_index=True,
                        help_text="When this record was created",
                    ),
                ),
                ("updated_at", models.DateTimeField(auto_now=True, help_text="When this record was last modified")),
                (
                    "deleted_at",
                    models.DateTimeField(
                        blank=True,
                        db_index=True,
                        help_text="Soft delete timestamp (null = active)",
                        null=True,
                    ),
                ),
                ("name", models.CharField(help_text="Cohort display name", max_length=100)),
                ("description", models.TextField(blank=True, default="")),
                (
                    "event",
                    models.ForeignKey(
                        help_text="Event this cohort belongs to",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="cohorts",
                        to="ctf.ctfevent",
                    ),
                ),
            ],
            options={
                "verbose_name": "CTF Cohort",
                "verbose_name_plural": "CTF Cohorts",
                "db_table": "ctf_cohort",
                "ordering": ["name"],
            },
        ),
        migrations.AddConstraint(
            model_name="ctfcohort",
            constraint=models.UniqueConstraint(
                condition=models.Q(("deleted_at__isnull", True)),
                fields=("event", "name"),
                name="unique_active_cohort_name_per_event",
            ),
        ),
        migrations.AddField(
            model_name="ctfparticipant",
            name="cohort",
            field=models.ForeignKey(
                blank=True,
                help_text="Stable event-owned cohort membership used by model-access selection",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="participants",
                to="ctf.ctfcohort",
            ),
        ),
        migrations.AddField(
            model_name="ctfsparerange",
            name="cohort",
            field=models.ForeignKey(
                blank=True,
                help_text="Optional cohort whose selector explicitly includes this spare",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="spare_ranges",
                to="ctf.ctfcohort",
            ),
        ),
        migrations.AddField(
            model_name="ctfsparerange",
            name="team",
            field=models.ForeignKey(
                blank=True,
                help_text="Optional team whose selector explicitly includes this spare",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="spare_ranges",
                to="ctf.ctfteam",
            ),
        ),
    ]
