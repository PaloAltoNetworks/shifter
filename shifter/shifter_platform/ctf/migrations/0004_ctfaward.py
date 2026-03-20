"""Add CTFAward model for organizer-granted score adjustments."""

import uuid

import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ctf", "0003_ctf_flag_model"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="CTFAward",
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
                (
                    "updated_at",
                    models.DateTimeField(
                        auto_now=True,
                        help_text="When this record was last modified",
                    ),
                ),
                (
                    "deleted_at",
                    models.DateTimeField(
                        blank=True,
                        db_index=True,
                        help_text="Soft delete timestamp (null = active)",
                        null=True,
                    ),
                ),
                (
                    "points",
                    models.IntegerField(
                        help_text="Points to add (positive) or deduct (negative)",
                        validators=[
                            django.core.validators.MinValueValidator(-10000),
                            django.core.validators.MaxValueValidator(10000),
                        ],
                    ),
                ),
                (
                    "reason",
                    models.TextField(
                        help_text="Organizer's explanation for the award",
                    ),
                ),
                (
                    "event",
                    models.ForeignKey(
                        help_text="Event this award belongs to",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="awards",
                        to="ctf.ctfevent",
                    ),
                ),
                (
                    "participant",
                    models.ForeignKey(
                        help_text="Participant receiving the award",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="awards",
                        to="ctf.ctfparticipant",
                    ),
                ),
                (
                    "granted_by",
                    models.ForeignKey(
                        help_text="User who granted the award",
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="ctf_awards_granted",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "CTF Award",
                "verbose_name_plural": "CTF Awards",
                "db_table": "ctf_award",
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="ctfaward",
            index=models.Index(
                fields=["event", "participant"],
                name="ctf_award_event_i_a1b2c3_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="ctfaward",
            index=models.Index(
                fields=["participant"],
                name="ctf_award_partici_d4e5f6_idx",
            ),
        ),
    ]
