"""Add UserProfile.organizer_grant_source (issue #1516).

Records the provenance of a user's ``CTF Organizer`` membership so login-time
provider reconciliation can revoke provider-derived authority when the
administrator-controlled provider evidence disappears, while preserving explicit
local (Django-admin / dev-login) assignments. See ``config.organizer_authority``.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("management", "0006_userprofile_cognito_groups"),
    ]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="organizer_grant_source",
            field=models.CharField(
                blank=True,
                choices=[("", "None"), ("provider", "Provider group"), ("local", "Local assignment")],
                default="",
                help_text=(
                    "Provenance of CTF Organizer membership (issue #1516): 'provider' is "
                    "auto-revoked when admin-controlled provider evidence disappears at "
                    "login; 'local' is an explicit local assignment and is never "
                    "auto-revoked. Empty when the user is not a tracked organizer."
                ),
                max_length=16,
            ),
        ),
    ]
