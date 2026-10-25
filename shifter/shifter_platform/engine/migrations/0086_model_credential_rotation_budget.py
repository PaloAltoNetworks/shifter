"""Bound authenticated credential rotation under the existing grant row lock."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("engine", "0085_raes_image_runtime_profiles")]

    operations = [
        migrations.AddField(
            model_name="modelaccesscredential", name="rotation_window_started_at", field=models.DateTimeField(null=True)
        ),
        migrations.AddField(
            model_name="modelaccesscredential", name="rotation_count", field=models.PositiveSmallIntegerField(default=0)
        ),
    ]
