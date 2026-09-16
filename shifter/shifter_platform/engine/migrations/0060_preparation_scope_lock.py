"""Serialize outstanding-work admission across immutable cloud grant versions."""

from django.db import migrations, models


class Migration(migrations.Migration):
    """A durable per-scope mutex; operation rows remain the capacity authority."""

    dependencies = [("engine", "0059_artifact_preparation_operations")]

    operations = [
        migrations.CreateModel(
            name="PreparationScopeLock",
            fields=[("scope_digest", models.CharField(max_length=71, primary_key=True, serialize=False))],
        ),
    ]
