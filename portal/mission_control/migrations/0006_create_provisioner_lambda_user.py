# Generated migration for provisioner Lambda database user
#
# This migration creates a PostgreSQL user for the provisioner Lambda functions
# to connect via IAM Database Authentication. The Lambda uses generate_db_auth_token()
# instead of a password.
#
# Requirements:
# - RDS must have iam_database_authentication_enabled = true
# - Lambda IAM role must have rds-db:connect permission for this user

from django.db import migrations


def create_provisioner_user(apps, schema_editor):
    """Create provisioner_lambda user on PostgreSQL only."""
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'provisioner_lambda') THEN
                CREATE USER provisioner_lambda;
            END IF;
        END
        $$;

        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'rds_iam') THEN
                EXECUTE 'GRANT rds_iam TO provisioner_lambda';
            END IF;
        END
        $$;

        GRANT CONNECT ON DATABASE shifter TO provisioner_lambda;
        GRANT USAGE ON SCHEMA public TO provisioner_lambda;
        GRANT SELECT ON mission_control_range TO provisioner_lambda;
        GRANT SELECT ON mission_control_agentconfig TO provisioner_lambda;
        GRANT UPDATE (
            status,
            subnet_id,
            subnet_cidr,
            victim_ip,
            victim_instance_id,
            chat_url,
            error_message,
            ready_at,
            destroyed_at
        ) ON mission_control_range TO provisioner_lambda;
    """)


def drop_provisioner_user(apps, schema_editor):
    """Drop provisioner_lambda user on PostgreSQL only."""
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("""
        REVOKE ALL PRIVILEGES ON mission_control_range FROM provisioner_lambda;
        REVOKE ALL PRIVILEGES ON mission_control_agentconfig FROM provisioner_lambda;
        REVOKE USAGE ON SCHEMA public FROM provisioner_lambda;
        REVOKE CONNECT ON DATABASE shifter FROM provisioner_lambda;

        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'rds_iam') THEN
                EXECUTE 'REVOKE rds_iam FROM provisioner_lambda';
            END IF;
        END
        $$;

        DROP USER IF EXISTS provisioner_lambda;
    """)


class Migration(migrations.Migration):
    """Create provisioner_lambda PostgreSQL user with IAM auth and minimal permissions."""

    dependencies = [
        (
            "mission_control",
            "0005_range_step_function_execution_arn_range_subnet_cidr_and_more",
        ),
    ]

    operations = [
        migrations.RunPython(create_provisioner_user, drop_provisioner_user),
    ]
