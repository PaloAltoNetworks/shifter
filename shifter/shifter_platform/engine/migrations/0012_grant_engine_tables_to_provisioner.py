# Grant provisioner_lambda access to Engine tables for NGFW operations.
#
# The provisioner needs to:
# - SELECT from engine_request (lookup by request_id)
# - SELECT/UPDATE on engine_instance (read state, update status/state)
# - SELECT/UPDATE on engine_app (read app_id, update status)
# - UPDATE on engine_subnet (update state/status)
#
# Also adds missing updated_at columns to engine_instance and engine_app.

from django.db import migrations, models


def grant_permissions(apps, schema_editor):
    """Grant Engine table permissions to provisioner_lambda."""
    if schema_editor.connection.vendor != "postgresql":
        return

    schema_editor.execute(
        """
        -- engine_request: SELECT only (lookup by request_id)
        GRANT SELECT ON engine_request TO provisioner_lambda;

        -- engine_instance: SELECT + UPDATE (status, state, timestamps)
        GRANT SELECT ON engine_instance TO provisioner_lambda;
        GRANT UPDATE ON engine_instance TO provisioner_lambda;

        -- engine_app: SELECT + UPDATE (status, timestamps)
        GRANT SELECT ON engine_app TO provisioner_lambda;
        GRANT UPDATE ON engine_app TO provisioner_lambda;

        -- engine_subnet: UPDATE only (state, status updates)
        GRANT UPDATE ON engine_subnet TO provisioner_lambda;
        """
    )


def revoke_permissions(apps, schema_editor):
    """Revoke Engine table permissions from provisioner_lambda."""
    if schema_editor.connection.vendor != "postgresql":
        return

    schema_editor.execute(
        """
        REVOKE SELECT ON engine_request FROM provisioner_lambda;
        REVOKE SELECT, UPDATE ON engine_instance FROM provisioner_lambda;
        REVOKE SELECT, UPDATE ON engine_app FROM provisioner_lambda;
        REVOKE UPDATE ON engine_subnet FROM provisioner_lambda;
        """
    )


class Migration(migrations.Migration):
    """Grant provisioner_lambda access to Engine tables for NGFW operations."""

    dependencies = [
        ("engine", "0011_add_instance_subnet_fk"),
    ]

    operations = [
        # Add updated_at column to engine_instance
        migrations.AddField(
            model_name="instance",
            name="updated_at",
            field=models.DateTimeField(auto_now=True),
        ),
        # Add updated_at column to engine_app
        migrations.AddField(
            model_name="app",
            name="updated_at",
            field=models.DateTimeField(auto_now=True),
        ),
        # Add updated_at column to engine_subnet
        migrations.AddField(
            model_name="subnet",
            name="updated_at",
            field=models.DateTimeField(auto_now=True),
        ),
        # Grant permissions
        migrations.RunPython(grant_permissions, revoke_permissions),
    ]
