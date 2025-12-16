# Generated migration for Victim MCP server database user
#
# This migration creates a PostgreSQL user for the victim mcp-shifter server
# to connect via IAM Database Authentication.
#
# The MCP server uses TARGET_MODE environment variable to determine which
# columns to query (victim_* vs kali_*). No schema/view tricks needed.
#
# Requirements:
# - RDS must have iam_database_authentication_enabled = true
# - EC2 IAM role must have rds-db:connect permission for this user

from django.db import migrations


class Migration(migrations.Migration):
    """Create victim_mcp_user for the victim MCP server."""

    dependencies = [
        ("mission_control", "0012_range_victim_ssh_key_secret_arn"),
        ("mission_control", "0012_add_cognito_sub_to_userprofile"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                -- Create user (no password - uses IAM auth)
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT FROM pg_roles WHERE rolname = 'victim_mcp_user'
                    ) THEN
                        CREATE USER victim_mcp_user;
                    END IF;
                END
                $$;

                -- Grant IAM authentication capability (only on RDS)
                DO $$
                BEGIN
                    IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'rds_iam') THEN
                        EXECUTE 'GRANT rds_iam TO victim_mcp_user';
                    END IF;
                END
                $$;

                -- Grant permissions
                GRANT CONNECT ON DATABASE shifter TO victim_mcp_user;
                GRANT USAGE ON SCHEMA public TO victim_mcp_user;
                GRANT SELECT ON public.mission_control_range TO victim_mcp_user;
                GRANT SELECT ON public.auth_user TO victim_mcp_user;
                GRANT SELECT ON public.mission_control_userprofile TO victim_mcp_user;
            """,
            reverse_sql="""
                -- Revoke all permissions
                REVOKE ALL PRIVILEGES ON public.mission_control_range
                    FROM victim_mcp_user;
                REVOKE ALL PRIVILEGES ON public.auth_user FROM victim_mcp_user;
                REVOKE ALL PRIVILEGES ON public.mission_control_userprofile
                    FROM victim_mcp_user;
                REVOKE USAGE ON SCHEMA public FROM victim_mcp_user;
                REVOKE CONNECT ON DATABASE shifter FROM victim_mcp_user;

                -- Revoke rds_iam only if it exists (RDS only)
                DO $$
                BEGIN
                    IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'rds_iam') THEN
                        EXECUTE 'REVOKE rds_iam FROM victim_mcp_user';
                    END IF;
                END
                $$;

                -- Drop user
                DROP USER IF EXISTS victim_mcp_user;
            """,
        ),
    ]
