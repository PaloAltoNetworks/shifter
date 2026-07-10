"""Add Cognito group snapshot to UserProfile for token-owner authorization checks."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("management", "0005_remove_ctf_event_fk"),
    ]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="cognito_groups",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="Cognito group names captured from verified OIDC claims at login",
            ),
        ),
    ]
