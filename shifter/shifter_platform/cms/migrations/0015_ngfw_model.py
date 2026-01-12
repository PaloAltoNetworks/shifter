"""Rename UserNGFW to NGFW and add ngfw_spec field.

UserNGFW → NGFW (state-only rename, same db_table).
Infrastructure fields moved to Engine NGFW model.
Add ngfw_spec JSONField for hydrated configuration.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("cms", "0014_add_app_models"),
        # Must run after engine removes Range.ngfw FK to cms.userngfw
        ("engine", "0004_remove_range_ngfw_fk"),
    ]

    operations = [
        # Step 1: Add ngfw_spec column to the table
        migrations.AddField(
            model_name="userngfw",
            name="ngfw_spec",
            field=models.JSONField(blank=True, null=True),
        ),
        # Step 2: Remove infrastructure columns (now in Engine NGFW)
        migrations.RemoveField(
            model_name="userngfw",
            name="instance_id",
        ),
        migrations.RemoveField(
            model_name="userngfw",
            name="mgmt_eni_id",
        ),
        migrations.RemoveField(
            model_name="userngfw",
            name="data_eni_id",
        ),
        migrations.RemoveField(
            model_name="userngfw",
            name="management_ip",
        ),
        migrations.RemoveField(
            model_name="userngfw",
            name="dataplane_ip",
        ),
        migrations.RemoveField(
            model_name="userngfw",
            name="gwlb_arn",
        ),
        migrations.RemoveField(
            model_name="userngfw",
            name="target_group_arn",
        ),
        migrations.RemoveField(
            model_name="userngfw",
            name="gwlb_service_name",
        ),
        migrations.RemoveField(
            model_name="userngfw",
            name="serial_number",
        ),
        migrations.RemoveField(
            model_name="userngfw",
            name="device_cert_status",
        ),
        migrations.RemoveField(
            model_name="userngfw",
            name="xdr_configured",
        ),
        migrations.RemoveField(
            model_name="userngfw",
            name="provisioned_at",
        ),
        migrations.RemoveField(
            model_name="userngfw",
            name="last_started_at",
        ),
        migrations.RemoveField(
            model_name="userngfw",
            name="last_stopped_at",
        ),
        # Step 3: Alter status field - different choices and default
        migrations.AlterField(
            model_name="userngfw",
            name="status",
            field=models.CharField(default="pending", max_length=20),
        ),
        # Step 4: Rename model in Django state (table name stays the same)
        migrations.RenameModel(
            old_name="UserNGFW",
            new_name="NGFW",
        ),
        # Step 5: Update model options
        migrations.AlterModelOptions(
            name="ngfw",
            options={
                "ordering": ["-created_at"],
                "verbose_name": "NGFW",
                "verbose_name_plural": "NGFWs",
            },
        ),
    ]
