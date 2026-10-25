"""GCP native application and policy SQL duty reconciliation on PostgreSQL."""

from __future__ import annotations

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import ProgrammingError, connection

pytestmark = [pytest.mark.openfga, pytest.mark.postgres, pytest.mark.django_db(transaction=True)]


def test_native_database_bootstrap_preserves_duties_and_removes_provider_defaults(monkeypatch):
    """Use PostgreSQL's real role inheritance and table ACL enforcement."""
    users = {
        role: f"synthetic-{role}@synthetic-project.iam"
        for role in ("portal", "workers", "ctf-scheduler", "provisioner-launcher", "provisioner")
    }
    with connection.cursor() as cursor:
        cursor.execute("CREATE ROLE cloudsqlsuperuser NOLOGIN CREATEROLE CREATEDB")
        for role in ("portal_runtime", "provisioner_runtime", "guacamole_admin"):
            cursor.execute(
                f'CREATE ROLE "{role}" LOGIN CREATEROLE CREATEDB'
                if role != "portal_runtime"
                else f'ALTER ROLE "{role}" CREATEROLE CREATEDB'
            )
            cursor.execute(f'GRANT cloudsqlsuperuser TO "{role}"')
        for user in users.values():
            cursor.execute('CREATE ROLE "' + user + '" LOGIN')
    monkeypatch.setenv("CLOUD_PROVIDER", "gcp")
    monkeypatch.setenv("DB_AUTH_MODE", "password")
    monkeypatch.setenv("GCP_DATABASE_IAM_USERS_JSON", __import__("json").dumps(users))
    monkeypatch.setenv("GCP_PROJECT_ID", "synthetic-project")
    monkeypatch.setenv("CLOUD_SQL_INSTANCE_CONNECTION_NAME", "synthetic-project:us-central1:platform-pg")
    try:
        call_command("reconcile_gcp_database_duties")
        call_command("reconcile_gcp_database_duties")
        with connection.cursor() as cursor:
            for role in ("portal_runtime", "provisioner_runtime", "guacamole_admin"):
                cursor.execute("SELECT rolcreaterole, rolcreatedb FROM pg_roles WHERE rolname=%s", [role])
                assert cursor.fetchone() == (False, False)
                cursor.execute("SELECT pg_has_role(%s, 'cloudsqlsuperuser', 'MEMBER')", [role])
                assert cursor.fetchone() == (False,)
            for user in users.values():
                cursor.execute("SELECT has_schema_privilege(%s, 'public', 'CREATE')", [user])
                assert cursor.fetchone() == (False,)
                cursor.execute("SELECT has_table_privilege(%s, 'django_migrations', 'UPDATE')", [user])
                assert cursor.fetchone() == ((False,) if user == users["provisioner"] else (True,))
                cursor.execute("SELECT has_table_privilege(%s, 'shared_auditlog', 'DELETE')", [user])
                assert cursor.fetchone() == (False,)
            cursor.execute('SET ROLE "' + users["provisioner"] + '"')
            with pytest.raises(ProgrammingError) as denied:
                cursor.execute("SELECT * FROM management_principal LIMIT 1")
            assert denied.value.__cause__.sqlstate == "42501"
    finally:
        # Roll back the denied statement before revoking/drop fixtures. Native
        # roles are instance-global even though test tables are database-local.
        connection.rollback()
        with connection.cursor() as cursor:
            cursor.execute("RESET ROLE")
            for user in users.values():
                cursor.execute('DROP OWNED BY "' + user + '"')
                cursor.execute('DROP ROLE "' + user + '"')
            for role in ("provisioner_runtime", "guacamole_admin", "cloudsqlsuperuser"):
                cursor.execute(f'DROP OWNED BY "{role}"')
                cursor.execute(f'DROP ROLE "{role}"')


def test_native_policy_migrator_owns_existing_datastore_without_application_access(monkeypatch):
    users = {
        role: f"synthetic-{role}@synthetic-project.iam"
        for role in (
            "portal",
            "workers",
            "ctf-scheduler",
            "provisioner-launcher",
            "provisioner",
            "openfga-runtime",
            "openfga-admin",
            "openfga-migrator",
        )
    }
    with connection.cursor() as cursor:
        for user in users.values():
            cursor.execute('CREATE ROLE "' + user + '" LOGIN')
    monkeypatch.setenv("CLOUD_PROVIDER", "gcp")
    monkeypatch.setenv("DB_AUTH_MODE", "password")
    monkeypatch.setenv("GCP_PROJECT_ID", "synthetic-project")
    monkeypatch.setenv("CLOUD_SQL_INSTANCE_CONNECTION_NAME", "synthetic-project:us-central1:platform-pg")
    monkeypatch.setenv("GCP_DATABASE_IAM_USERS_JSON", __import__("json").dumps(users))
    try:
        call_command("reconcile_gcp_database_duties")
        call_command("reconcile_gcp_database_duties")
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database()")
            application_database = cursor.fetchone()[0]
            for role in ("openfga-runtime", "openfga-admin", "openfga-migrator"):
                cursor.execute("SELECT has_database_privilege(%s, %s, 'CONNECT')", [users[role], application_database])
                assert cursor.fetchone() == (False,)
        import psycopg

        with (
            psycopg.connect(**{**connection.get_connection_params(), "dbname": "openfga"}) as policy,
            policy.cursor() as cursor,
        ):
            cursor.execute("SELECT has_table_privilege(%s, 'goose_db_version', 'UPDATE')", [users["openfga-migrator"]])
            assert cursor.fetchone() == (True,)
            cursor.execute(
                "SELECT rolcreaterole, rolcreatedb FROM pg_roles WHERE rolname=%s", [users["openfga-migrator"]]
            )
            assert cursor.fetchone() == (False, False)
            cursor.execute('GRANT CONNECT ON DATABASE openfga TO "' + users["portal"] + '"')
        try:
            with pytest.raises(CommandError, match="SQL duty reconciliation failed"):
                call_command("reconcile_gcp_database_duties")
        finally:
            with psycopg.connect(**{**connection.get_connection_params(), "dbname": "openfga"}) as policy:
                policy.execute('REVOKE CONNECT ON DATABASE openfga FROM "' + users["portal"] + '"')
    finally:
        with connection.cursor() as cursor:
            for user in users.values():
                cursor.execute('DROP OWNED BY "' + user + '"')
                cursor.execute('DROP ROLE "' + user + '"')
