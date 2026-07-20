from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("engine", "0029_range_backend_ownership_binding")]

    operations = [
        migrations.AddField(
            model_name="range",
            name="vpn_access_binding",
            field=models.JSONField(
                blank=True,
                help_text=(
                    "Non-secret generation-bound OpenVPN access binding; profile material stays in provider secrets"
                ),
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="range",
            name="remote_access_capability",
            field=models.JSONField(
                blank=True,
                help_text="Server-issued non-secret authorization for optional range remote access",
                null=True,
            ),
        ),
    ]
