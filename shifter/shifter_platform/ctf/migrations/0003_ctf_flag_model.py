"""Add CTFFlag model for multiple flags per challenge."""

import uuid

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("ctf", "0002_ctfevent_range_config"),
    ]

    operations = [
        migrations.CreateModel(
            name="CTFFlag",
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
                    "flag_hash",
                    models.CharField(
                        help_text="Hashed flag value (static) or regex pattern (regex type)",
                        max_length=255,
                    ),
                ),
                (
                    "flag_type",
                    models.CharField(
                        choices=[
                            ("static", "Static (hashed comparison)"),
                            ("regex", "Regex (pattern match)"),
                        ],
                        default="static",
                        help_text="Flag verification type",
                        max_length=10,
                    ),
                ),
                (
                    "case_sensitive",
                    models.BooleanField(
                        default=True,
                        help_text="Whether flag comparison is case-sensitive",
                    ),
                ),
                (
                    "order",
                    models.PositiveIntegerField(
                        default=0,
                        help_text="Display order in admin UI",
                    ),
                ),
                (
                    "challenge",
                    models.ForeignKey(
                        help_text="Challenge this flag belongs to",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="flags",
                        to="ctf.ctfchallenge",
                    ),
                ),
            ],
            options={
                "verbose_name": "CTF Flag",
                "verbose_name_plural": "CTF Flags",
                "db_table": "ctf_flag",
                "ordering": ["order", "created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="ctfflag",
            index=models.Index(
                fields=["challenge", "flag_type"],
                name="ctf_flag_challen_d1c5e7_idx",
            ),
        ),
    ]
