# Generated migration for MCP server database user
#
# This migration creates a PostgreSQL user for the mcp-shifter server
# to connect via IAM Database Authentication. The server uses RDS Signer
# to generate auth tokens instead of a password.
#
# Requirements:
# - RDS must have iam_database_authentication_enabled = true
# - EC2 IAM role must have rds-db:connect permission for this user

from django.db import migrations


def create_mcp_user(apps, schema_editor):
    """Create mcp_user on PostgreSQL only."""
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'mcp_user') THEN
                CREATE USER mcp_user;
            END IF;
        END
        $$;

        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'rds_iam') THEN
                EXECUTE 'GRANT rds_iam TO mcp_user';
            END IF;
        END
        $$;

        GRANT CONNECT ON DATABASE shifter TO mcp_user;
        GRANT USAGE ON SCHEMA public TO mcp_user;
        GRANT SELECT ON mission_control_range TO mcp_user;
        GRANT SELECT ON auth_user TO mcp_user;
    """)


def drop_mcp_user(apps, schema_editor):
    """Drop mcp_user on PostgreSQL only."""
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("""
        REVOKE ALL PRIVILEGES ON mission_control_range FROM mcp_user;
        REVOKE ALL PRIVILEGES ON auth_user FROM mcp_user;
        REVOKE USAGE ON SCHEMA public FROM mcp_user;
        REVOKE CONNECT ON DATABASE shifter FROM mcp_user;

        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'rds_iam') THEN
                EXECUTE 'REVOKE rds_iam FROM mcp_user';
            END IF;
        END
        $$;

        DROP USER IF EXISTS mcp_user;
    """)


class Migration(migrations.Migration):
    """Create mcp_user PostgreSQL user with IAM auth and read-only Range permissions."""

    dependencies = [
        (
            "mission_control",
            "0010_range_kali_ssh_key_secret_arn",
        ),
    ]

    operations = [
        migrations.RunPython(create_mcp_user, drop_mcp_user),
    ]
