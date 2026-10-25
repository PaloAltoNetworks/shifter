"""Unit coverage for the provision_guacamole_database management command.

The command runs as a one-shot in-cluster Job on AWS EKS to create the guacamole
database + guacamole_admin role on the shared RDS instance. These tests exercise
its idempotent branches (create vs. re-sync role, create vs. skip database) and
the injection-safe password literal, with the Secrets Manager store and the
psycopg connection replaced by fixtures (no live database, no per-assertion mocks).
"""

from __future__ import annotations

import json
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from psycopg import sql

MODULE = "mission_control.management.commands.provision_guacamole_database"

_MASTER = {
    "host": "dev-portal-db.example.us-east-2.rds.amazonaws.com",
    "port": 5432,
    "username": "shifter_admin",
    "password": "master-pw",
    "dbname": "shifter",
}
_GUACAMOLE = {"username": "guacamole_admin", "password": "guac-secret-pw", "dbname": "guacamole"}


class _FakeCursor:
    def __init__(self, role_exists: bool, database_exists: bool) -> None:
        self._results: list[tuple[int] | None] = [
            (1,) if role_exists else None,
            (1,) if database_exists else None,
        ]
        self.executed: list[object] = []
        self._pending: tuple[int] | None = None

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, query: object, params: object | None = None) -> None:
        self.executed.append(query)
        text = query if isinstance(query, str) else ""
        if isinstance(text, str) and text.startswith("SELECT 1 FROM"):
            self._pending = self._results.pop(0)

    def fetchone(self) -> tuple[int] | None:
        return self._pending


class _FakeConnection:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor
        self.closed = False
        self.connect_kwargs: dict[str, object] = {}

    def cursor(self) -> _FakeCursor:
        return self._cursor

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def patched(monkeypatch):
    """Patch the secrets store + psycopg.connect; return a builder for the fixture."""

    def _build(*, role_exists: bool, database_exists: bool, env: dict[str, str] | None = None):
        for key in (
            "DB_SECRET_ID",
            "DB_SECRET_ARN",
            "GUACAMOLE_DB_SECRET_ID",
            "GUACAMOLE_DB_SECRET_ARN",
            "DB_HOST",
            "DB_PORT",
        ):
            monkeypatch.delenv(key, raising=False)
        for key, value in (env or {"DB_SECRET_ID": "master-arn", "GUACAMOLE_DB_SECRET_ID": "guac-arn"}).items():
            monkeypatch.setenv(key, value)

        payloads = {
            "master-arn": json.dumps(_MASTER),
            "guac-arn": json.dumps(_GUACAMOLE),
        }

        class _Store:
            def get_secret(self, secret_ref: str) -> str:
                return payloads[secret_ref]

        monkeypatch.setattr(f"{MODULE}.get_secrets_store", lambda: _Store())

        cursor = _FakeCursor(role_exists=role_exists, database_exists=database_exists)
        connection = _FakeConnection(cursor)

        def _connect(**kwargs: object) -> _FakeConnection:
            connection.connect_kwargs = kwargs
            return connection

        monkeypatch.setattr(f"{MODULE}.psycopg.connect", _connect)
        return cursor, connection

    return _build


def _run() -> str:
    out = StringIO()
    call_command("provision_guacamole_database", stdout=out)
    return out.getvalue()


def _rendered(cursor: _FakeCursor) -> list[str]:
    return [q.as_string(None) if isinstance(q, sql.Composed) else str(q) for q in cursor.executed]


def test_creates_role_and_database_when_absent(patched):
    cursor, connection = patched(role_exists=False, database_exists=False)
    output = _run()
    rendered = _rendered(cursor)
    assert any('CREATE ROLE "guacamole_admin" WITH LOGIN PASSWORD' in q for q in rendered)
    assert any('CREATE DATABASE "guacamole" OWNER "guacamole_admin"' in q for q in rendered)
    # The password is embedded as a quoted literal, never a bound param on argv.
    assert any("'guac-secret-pw'" in q for q in rendered)
    assert connection.connect_kwargs["autocommit"] is True
    assert connection.connect_kwargs["user"] == "shifter_admin"
    assert connection.closed is True
    assert "provisioned" in output


def test_alters_role_password_and_skips_existing_database(patched):
    cursor, _ = patched(role_exists=True, database_exists=True)
    _run()
    rendered = _rendered(cursor)
    assert any('ALTER ROLE "guacamole_admin" WITH LOGIN PASSWORD' in q for q in rendered)
    assert not any(q.startswith("CREATE DATABASE") for q in rendered)


def test_requires_both_secret_ids(patched):
    patched(role_exists=False, database_exists=False, env={"DB_SECRET_ID": "master-arn"})
    with pytest.raises(CommandError):
        call_command("provision_guacamole_database")
