# Separate provisioning and teardown ECS task ARNs on Range.

from django.db import migrations, models

TEARDOWN_STATUSES = frozenset({"destroying", "destroyed"})


def _backfill_task_arns(apps, schema_editor):
    range_model = apps.get_model("engine", "Range")
    for row in range_model.objects.exclude(step_function_execution_arn="").iterator():
        legacy_arn = row.step_function_execution_arn
        if row.status in TEARDOWN_STATUSES:
            row.teardown_task_arn = legacy_arn
        else:
            row.provisioning_task_arn = legacy_arn
        row.save(update_fields=["provisioning_task_arn", "teardown_task_arn"])


class Migration(migrations.Migration):
    dependencies = [
        ("engine", "0021_wrap_persisted_spec_discriminators"),
    ]

    operations = [
        migrations.AddField(
            model_name="range",
            name="provisioning_task_arn",
            field=models.CharField(
                blank=True,
                default="",
                help_text="ECS/GCP task identifier for the provisioning operation",
                max_length=500,
            ),
        ),
        migrations.AddField(
            model_name="range",
            name="teardown_task_arn",
            field=models.CharField(
                blank=True,
                default="",
                help_text="ECS/GCP task identifier for the teardown operation",
                max_length=500,
            ),
        ),
        migrations.AlterField(
            model_name="range",
            name="step_function_execution_arn",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Legacy ECS task ARN (deprecated)",
                max_length=500,
            ),
        ),
        migrations.RunPython(_backfill_task_arns, migrations.RunPython.noop),
    ]
