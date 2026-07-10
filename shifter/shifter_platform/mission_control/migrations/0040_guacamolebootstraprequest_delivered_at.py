from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("mission_control", "0039_guacamole_bootstrap_request"),
    ]

    operations = [
        migrations.AddField(
            model_name="guacamolebootstraprequest",
            name="delivered_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
