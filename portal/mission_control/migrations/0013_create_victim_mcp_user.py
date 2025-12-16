# Generated migration for Victim MCP server database user
#
# This migration creates a PostgreSQL user for the victim mcp-shifter server
# to connect via IAM Database Authentication. It uses a schema trick to make
# the same MCP code work for both Kali and Victim by aliasing columns.
#
# The key insight: MCP queries `mission_control_range` for kali_ip, etc.
# By creating a view in victim_schema with the same table name that aliases
# victim columns to kali column names, and setting the user's search_path,
# the MCP code sees victim data as if it were kali data.
#
# Requirements:
# - RDS must have iam_database_authentication_enabled = true
# - EC2 IAM role must have rds-db:connect permission for this user

from django.db import migrations


class Migration(migrations.Migration):
    """Create victim_mcp_user with schema-based view aliasing."""

    dependencies = [
        ("mission_control", "0012_range_victim_ssh_key_secret_arn"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                -- Create schema for victim-specific views
                CREATE SCHEMA IF NOT EXISTS victim_schema;

                -- Create view with SAME NAME as base table
                -- This aliases victim columns to kali column names
                -- MCP queries "mission_control_range" and gets this view
                CREATE OR REPLACE VIEW victim_schema.mission_control_range AS
                SELECT
                    r.id,
                    r.user_id,
                    r.status,
                    r.victim_ip AS kali_ip,
                    r.victim_instance_id AS kali_instance_id,
                    r.victim_ssh_key_secret_arn AS kali_ssh_key_secret_arn,
                    r.chat_url,
                    r.created_at,
                    r.updated_at
                FROM public.mission_control_range r;

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

                -- Set search_path so victim_schema tables are found first
                -- This makes "mission_control_range" resolve to our view
                ALTER USER victim_mcp_user SET search_path TO victim_schema, public;

                -- Grant permissions
                GRANT CONNECT ON DATABASE shifter TO victim_mcp_user;
                GRANT USAGE ON SCHEMA victim_schema TO victim_mcp_user;
                GRANT USAGE ON SCHEMA public TO victim_mcp_user;
                GRANT SELECT ON victim_schema.mission_control_range TO victim_mcp_user;
                GRANT SELECT ON public.auth_user TO victim_mcp_user;
                GRANT SELECT ON public.mission_control_userprofile TO victim_mcp_user;
            """,
            reverse_sql="""
                -- Revoke all permissions
                REVOKE ALL PRIVILEGES ON victim_schema.mission_control_range
                    FROM victim_mcp_user;
                REVOKE ALL PRIVILEGES ON public.auth_user FROM victim_mcp_user;
                REVOKE ALL PRIVILEGES ON public.mission_control_userprofile
                    FROM victim_mcp_user;
                REVOKE USAGE ON SCHEMA victim_schema FROM victim_mcp_user;
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

                -- Drop view and schema
                DROP VIEW IF EXISTS victim_schema.mission_control_range;
                DROP SCHEMA IF EXISTS victim_schema;
            """,
        ),
    ]
