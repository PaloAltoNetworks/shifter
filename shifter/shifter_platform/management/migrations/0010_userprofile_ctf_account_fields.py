"""Add immutable CTF account origin and forced-password-change state."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("management", "0009_userprofile_issuer")]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="is_ctf_account",
            field=models.BooleanField(
                default=False,
                help_text="Immutable origin marker for temporary local CTF participant accounts",
            ),
        ),
        migrations.AddField(
            model_name="userprofile",
            name="must_change_password",
            field=models.BooleanField(
                default=False,
                help_text="Require a temporary CTF account to change its bootstrap password",
            ),
        ),
        migrations.AddConstraint(
            model_name="userprofile",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(is_ctf_account=False)
                    | models.Q(user_type="ctf_participant", cognito_sub__isnull=True, issuer="")
                ),
                name="ctf_account_profile_identity_invariants",
            ),
        ),
    ]
