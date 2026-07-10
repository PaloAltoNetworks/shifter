from django.db import migrations
from django.db.migrations.recorder import MigrationRecorder

EXPERIMENT_TABLES = (
    "experiments_runartifact",
    "experiments_experimentartifact",
    "experiments_experimentscript",
    "experiments_experimentrun",
    "experiments_experiment",
    "experiments_scriptasset",
)


def remove_legacy_experiments(apps, schema_editor):
    suffix = " CASCADE" if schema_editor.connection.vendor == "postgresql" else ""
    with schema_editor.connection.cursor() as cursor:
        for table in EXPERIMENT_TABLES:
            cursor.execute(f"DROP TABLE IF EXISTS {schema_editor.quote_name(table)}{suffix}")

    content_type = apps.get_model("contenttypes", "ContentType")
    content_type.objects.using(schema_editor.connection.alias).filter(app_label="experiments").delete()
    MigrationRecorder(schema_editor.connection).migration_qs.filter(app="experiments").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("cms", "0033_backfill_ctf_range_source"),
    ]

    operations = [
        migrations.RunPython(remove_legacy_experiments, migrations.RunPython.noop),
    ]
