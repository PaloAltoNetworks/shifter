# Generated migration to rename mcp_user to kali_mcp_user
#
# This migration renames the mcp_user PostgreSQL user to kali_mcp_user
# for consistency with victim_mcp_user. Each MCP container uses its own
# database user for operational isolation (logging, independent revocation).
#
# Requirements:
# - Migration 0011 must have created mcp_user
# - RDS must have iam_database_authentication_enabled = true

from django.db import migrations


class Migration(migrations.Migration):
    """Rename mcp_user to kali_mcp_user for consistency with victim_mcp_user."""

    dependencies = [
        ("mission_control", "0013_create_victim_mcp_user"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                -- Rename the user
                -- Note: mcp_user already has SELECT on mission_control_userprofile
                -- from migration 0012_add_cognito_sub_to_userprofile
                ALTER USER mcp_user RENAME TO kali_mcp_user;
            """,
            reverse_sql="""
                -- Rename back
                ALTER USER kali_mcp_user RENAME TO mcp_user;
            """,
        ),
    ]
