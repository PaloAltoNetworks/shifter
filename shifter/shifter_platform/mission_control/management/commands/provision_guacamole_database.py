"""Provision the Guacamole PostgreSQL database and role on the shared RDS (idempotent).

AWS RDS exposes no native Terraform user/database resource and the deploy runner
has no network path to the portal RDS, so on AWS EKS the ``guacamole_admin``
password role and its dedicated database are created from inside the cluster by
this command, run as a one-shot Job before the shifter chart is installed
(``scripts/bootstrap/aws_eks.py``). It connects to RDS as the master user and,
idempotently:

  * creates (or re-syncs the password of) the ``guacamole_admin`` LOGIN role, and
  * creates the ``guacamole`` database owned by that role,

so guacamole-client can connect with ``POSTGRESQL_USER``/``POSTGRESQL_PASSWORD``
and run its own schema initialisation (the guacamole image entrypoint's
``initdb.sh``). Credentials are read from Secrets Manager, never passed on argv;
the role password is emitted as a quoted SQL literal via ``psycopg.sql`` so it is
injection-safe, and ``CREATE DATABASE`` runs outside a transaction (autocommit).

GCP provisions the equivalent objects declaratively in Terraform (``google_sql_user``
/ ``google_sql_database``); this command is the AWS-side equivalent.
"""

from __future__ import annotations

import json
import os
from typing import Any

import psycopg
from django.core.management.base import BaseCommand, CommandError
from psycopg import Cursor, sql

from shared.cloud import get_secrets_store


class Command(BaseCommand):
    """Create the guacamole database + guacamole_admin role on the shared RDS (idempotent)."""

    help = "Idempotently create the guacamole database and guacamole_admin role on the shared RDS instance."

    def handle(self, *args: Any, **options: Any) -> None:
        db_secret_id = os.environ.get("DB_SECRET_ID") or os.environ.get("DB_SECRET_ARN")
        guacamole_secret_id = os.environ.get("GUACAMOLE_DB_SECRET_ID") or os.environ.get("GUACAMOLE_DB_SECRET_ARN")
        if not db_secret_id:
            raise CommandError("DB_SECRET_ID is required (master RDS credentials).")
        if not guacamole_secret_id:
            raise CommandError("GUACAMOLE_DB_SECRET_ID is required (guacamole credentials).")

        store = get_secrets_store()
        master = json.loads(store.get_secret(db_secret_id))
        guacamole = json.loads(store.get_secret(guacamole_secret_id))

        role = guacamole["username"]
        password = guacamole["password"]
        database = guacamole["dbname"]

        connection = psycopg.connect(
            host=os.environ.get("DB_HOST") or master["host"],
            port=str(os.environ.get("DB_PORT") or master.get("port", 5432)),
            user=master["username"],
            password=master["password"],
            dbname=master["dbname"],
            connect_timeout=15,
            autocommit=True,
        )
        try:
            with connection.cursor() as cursor:
                self._ensure_role(cursor, role, password)
                self._ensure_database(cursor, database, role)
        finally:
            connection.close()

        self.stdout.write(self.style.SUCCESS(f"Guacamole database {database!r} and role {role!r} are provisioned."))

    def _ensure_role(self, cursor: Cursor, role: str, password: str) -> None:
        """Create the guacamole_admin LOGIN role or re-sync its password to the secret."""
        cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,))
        action = "ALTER" if cursor.fetchone() is not None else "CREATE"
        # `action` is a fixed literal chosen here (never user input); the role name
        # is a quoted identifier and the password a quoted literal, so neither can
        # inject SQL.
        cursor.execute(
            sql.SQL("{action} ROLE {role} WITH LOGIN PASSWORD {password}").format(
                action=sql.SQL(action),
                role=sql.Identifier(role),
                password=sql.Literal(password),
            )
        )
        self.stdout.write(f"{action.title()}d role {role!r}.")

    def _ensure_database(self, cursor: Cursor, database: str, owner: str) -> None:
        """Create the dedicated guacamole database owned by guacamole_admin, if absent."""
        cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (database,))
        if cursor.fetchone() is not None:
            self.stdout.write(f"Database {database!r} already exists.")
            return
        # CREATE DATABASE cannot run inside a transaction (autocommit is set on the
        # connection) and its name/owner cannot be bound parameters, so quote them
        # as identifiers.
        cursor.execute(
            sql.SQL("CREATE DATABASE {database} OWNER {owner}").format(
                database=sql.Identifier(database),
                owner=sql.Identifier(owner),
            )
        )
        self.stdout.write(f"Created database {database!r} owned by {owner!r}.")
