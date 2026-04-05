"""Add CTFEmailTemplate model for per-event email customisation."""

from __future__ import annotations

import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("ctf", "0021_add_scoreboard_visible"),
    ]

    operations = [
        migrations.CreateModel(
            name="CTFEmailTemplate",
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
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "deleted_at",
                    models.DateTimeField(
                        blank=True,
                        db_index=True,
                        default=None,
                        help_text="Soft-delete timestamp",
                        null=True,
                    ),
                ),
                (
                    "notification_type",
                    models.CharField(
                        choices=[
                            ("invite", "Invite"),
                            ("credentials", "Credentials"),
                            ("reminder", "Reminder"),
                            ("announcement", "Announcement"),
                            ("event_start", "Event Start"),
                            ("event_end", "Event End"),
                            ("provision_failure", "Provision Failure"),
                        ],
                        help_text="Notification type this template overrides",
                        max_length=20,
                    ),
                ),
                (
                    "subject",
                    models.CharField(
                        blank=True,
                        default="",
                        help_text="Custom subject line (leave blank to use default)",
                        max_length=200,
                    ),
                ),
                (
                    "html_body",
                    models.TextField(
                        help_text="Custom HTML email body (Django template syntax)",
                    ),
                ),
                (
                    "text_body",
                    models.TextField(
                        help_text="Custom plain-text email body (Django template syntax)",
                    ),
                ),
                (
                    "event",
                    models.ForeignKey(
                        help_text="Event this template belongs to",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="email_templates",
                        to="ctf.ctfevent",
                    ),
                ),
            ],
            options={
                "verbose_name": "CTF Email Template",
                "verbose_name_plural": "CTF Email Templates",
                "db_table": "ctf_email_template",
                "ordering": ["notification_type"],
            },
        ),
        migrations.AddConstraint(
            model_name="ctfemailtemplate",
            constraint=models.UniqueConstraint(
                condition=models.Q(("deleted_at__isnull", True)),
                fields=("event", "notification_type"),
                name="unique_active_email_template_per_event_type",
            ),
        ),
    ]
