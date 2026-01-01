"""Initial migration for management models.

This migration uses SeparateDatabaseAndState to register UserProfile and
ActivityLog models in the management app without creating new tables.
The tables already exist as mission_control_userprofile and
mission_control_activitylog from the mission_control app.
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("mission_control", "0001_initial_models"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name="UserProfile",
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
                            "cognito_sub",
                            models.CharField(
                                blank=True,
                                db_index=True,
                                help_text="Cognito user pool subject identifier (UUID)",
                                max_length=36,
                                null=True,
                                unique=True,
                            ),
                        ),
                        ("deleted_at", models.DateTimeField(blank=True, null=True)),
                        ("anonymized_at", models.DateTimeField(blank=True, null=True)),
                        (
                            "user",
                            models.OneToOneField(
                                on_delete=django.db.models.deletion.CASCADE,
                                related_name="profile",
                                to=settings.AUTH_USER_MODEL,
                            ),
                        ),
                    ],
                    options={
                        "verbose_name": "User Profile",
                        "verbose_name_plural": "User Profiles",
                        "db_table": "mission_control_userprofile",
                    },
                ),
                migrations.CreateModel(
                    name="ActivityLog",
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
                        ("action", models.CharField(db_index=True, max_length=100)),
                        ("timestamp", models.DateTimeField(auto_now_add=True, db_index=True)),
                        ("metadata", models.JSONField(blank=True, default=dict)),
                        (
                            "user",
                            models.ForeignKey(
                                blank=True,
                                null=True,
                                on_delete=django.db.models.deletion.SET_NULL,
                                related_name="activities",
                                to=settings.AUTH_USER_MODEL,
                            ),
                        ),
                    ],
                    options={
                        "verbose_name": "Activity Log",
                        "verbose_name_plural": "Activity Logs",
                        "db_table": "mission_control_activitylog",
                        "ordering": ["-timestamp"],
                    },
                ),
            ],
            database_operations=[],
        ),
    ]
