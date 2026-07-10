# Generated migration for the portal runtime database user
#
# Creates a PostgreSQL user the running portal (web + workers) uses to connect
# via RDS IAM Database Authentication, so the runtime holds no long-lived
# database password (issue #159). The existing master user keeps schema
# ownership and runs migrations; this user gets broad DML on the application
# schema (but not DDL/ownership), mirroring the dedicated-IAM-user pattern in
# 0006_create_provisioner_lambda_user / 0011_create_mcp_user.
#
# Requirements:
# - RDS must have iam_database_authentication_enabled = true
# - The portal instance IAM role must have rds-db:connect for this user
#   (platform/terraform/modules/portal/ec2)

from django.db import migrations

# Role/schema grants that do not reference the database name. Fixed role
# literal, no interpolation, so this is plain (non-formatted) SQL.
_CREATE_SQL = """
    DO $$
    BEGIN
        IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'portal_runtime') THEN
            CREATE USER portal_runtime;
        END IF;
    END
    $$;

    DO $$
    BEGIN
        IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'rds_iam') THEN
            EXECUTE 'GRANT rds_iam TO portal_runtime';
        END IF;
    END
    $$;

    GRANT USAGE ON SCHEMA public TO portal_runtime;

    -- Existing application tables/sequences.
    GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO portal_runtime;
    GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO portal_runtime;

    -- Tables/sequences created by future migrations (run by the owner that
    -- executes this migration) inherit the same runtime DML automatically.
    ALTER DEFAULT PRIVILEGES IN SCHEMA public
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO portal_runtime;
    ALTER DEFAULT PRIVILEGES IN SCHEMA public
        GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO portal_runtime;
"""

_DROP_SQL = """
    ALTER DEFAULT PRIVILEGES IN SCHEMA public
        REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM portal_runtime;
    ALTER DEFAULT PRIVILEGES IN SCHEMA public
        REVOKE USAGE, SELECT, UPDATE ON SEQUENCES FROM portal_runtime;

    REVOKE SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public FROM portal_runtime;
    REVOKE USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public FROM portal_runtime;
    REVOKE USAGE ON SCHEMA public FROM portal_runtime;

    DO $$
    BEGIN
        IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'rds_iam') THEN
            EXECUTE 'REVOKE rds_iam FROM portal_runtime';
        END IF;
    END
    $$;

    DROP USER IF EXISTS portal_runtime;
"""


def _quoted_database(schema_editor):
    """Return the configured database name as a quoted SQL identifier."""
    return schema_editor.connection.ops.quote_name(schema_editor.connection.settings_dict["NAME"])


def create_portal_runtime_user(apps, schema_editor):
    """Create the portal_runtime user with IAM auth and schema-wide DML."""
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(_CREATE_SQL)
    # Database-scoped grant: the only interpolated value is a quote_name()'d
    # identifier from settings (DB_NAME), never user input, and a database name
    # cannot be passed as a bound parameter in DDL.
    database = _quoted_database(schema_editor)
    schema_editor.execute(f"GRANT CONNECT ON DATABASE {database} TO portal_runtime;")  # nosec B608


def drop_portal_runtime_user(apps, schema_editor):
    """Reverse: revoke privileges and drop the portal_runtime user."""
    if schema_editor.connection.vendor != "postgresql":
        return
    database = _quoted_database(schema_editor)
    schema_editor.execute(f"REVOKE CONNECT ON DATABASE {database} FROM portal_runtime;")  # nosec B608
    schema_editor.execute(_DROP_SQL)


class Migration(migrations.Migration):
    """Create the portal_runtime PostgreSQL user for IAM-authenticated runtime."""

    dependencies = [
        ("mission_control", "0040_guacamolebootstraprequest_delivered_at"),
    ]

    operations = [
        migrations.RunPython(create_portal_runtime_user, drop_portal_runtime_user),
    ]
