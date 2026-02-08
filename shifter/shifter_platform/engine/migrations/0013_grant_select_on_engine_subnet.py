# Grant SELECT on engine_subnet to provisioner_lambda.
# UPDATE alone isn't sufficient - need SELECT to find rows to update.

from django.db import migrations


def grant_select(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("GRANT SELECT ON engine_subnet TO provisioner_lambda;")


def revoke_select(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("REVOKE SELECT ON engine_subnet FROM provisioner_lambda;")


class Migration(migrations.Migration):
    dependencies = [
        ("engine", "0012_grant_engine_tables_to_provisioner"),
    ]

    operations = [
        migrations.RunPython(grant_select, revoke_select),
    ]
