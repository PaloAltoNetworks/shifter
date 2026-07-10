"""Tests for DATABASES construction (issue #159).

Covers the SQLite test path and the deployed PostgreSQL path with and without
RDS IAM authentication.
"""

from __future__ import annotations

import pytest
from django.core.exceptions import ImproperlyConfigured

from config._database_settings import _build_databases


def _clear_db_env(monkeypatch):
    for var in (
        "TESTING",
        "ENVIRONMENT",
        "DJANGO_DEBUG",
        "DB_IAM_AUTH",
        "DB_SSLMODE",
        "DB_SSL_ROOT_CERT",
        "DB_NAME",
        "DB_USER",
        "DB_PASSWORD",
        "DB_HOST",
        "DB_PORT",
    ):
        monkeypatch.delenv(var, raising=False)


def _set_postgres_env(monkeypatch, *, password: bool = True):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("DJANGO_DEBUG", "false")
    monkeypatch.setenv("DB_NAME", "shifter")
    monkeypatch.setenv("DB_USER", "portal")
    monkeypatch.setenv("DB_HOST", "db.example.internal")
    monkeypatch.setenv("DB_PORT", "5432")
    if password:
        monkeypatch.setenv("DB_PASSWORD", "postgres-secret")


def test_testing_uses_sqlite(monkeypatch):
    _clear_db_env(monkeypatch)
    monkeypatch.setenv("TESTING", "1")
    default = _build_databases()["default"]
    assert default["ENGINE"] == "django.db.backends.sqlite3"


def test_password_path_uses_stock_backend(monkeypatch):
    _clear_db_env(monkeypatch)
    _set_postgres_env(monkeypatch)
    default = _build_databases()["default"]
    assert default["ENGINE"] == "django.db.backends.postgresql"
    assert default["NAME"] == "shifter"
    assert default["USER"] == "portal"
    assert default["HOST"] == "db.example.internal"
    assert default["PORT"] == "5432"
    assert "sslmode" not in default["OPTIONS"]


def test_password_path_requires_database_env(monkeypatch):
    _clear_db_env(monkeypatch)
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("DJANGO_DEBUG", "false")

    with pytest.raises(ImproperlyConfigured, match="DB_NAME"):
        _build_databases()


def test_iam_path_uses_iam_backend_and_requires_ssl(monkeypatch):
    _clear_db_env(monkeypatch)
    _set_postgres_env(monkeypatch, password=False)
    monkeypatch.setenv("DB_IAM_AUTH", "true")
    default = _build_databases()["default"]
    assert default["ENGINE"] == "config.db_backends.rds_iam"
    assert default["OPTIONS"]["sslmode"] == "require"
    assert "sslrootcert" not in default["OPTIONS"]


def test_iam_path_honours_sslmode_and_root_cert(monkeypatch):
    _clear_db_env(monkeypatch)
    _set_postgres_env(monkeypatch, password=False)
    monkeypatch.setenv("DB_IAM_AUTH", "true")
    monkeypatch.setenv("DB_SSLMODE", "verify-full")
    monkeypatch.setenv("DB_SSL_ROOT_CERT", "/etc/ssl/rds-ca.pem")
    options = _build_databases()["default"]["OPTIONS"]
    assert options["sslmode"] == "verify-full"
    assert options["sslrootcert"] == "/etc/ssl/rds-ca.pem"


@pytest.mark.parametrize("value", ["false", "0", "", "no"])
def test_iam_disabled_for_non_true_values(monkeypatch, value):
    _clear_db_env(monkeypatch)
    _set_postgres_env(monkeypatch)
    monkeypatch.setenv("DB_IAM_AUTH", value)
    assert _build_databases()["default"]["ENGINE"] == "django.db.backends.postgresql"


def test_build_environment_uses_synthetic_database_defaults(monkeypatch):
    _clear_db_env(monkeypatch)
    monkeypatch.setenv("ENVIRONMENT", "build")

    default = _build_databases()["default"]

    assert default["NAME"] == "shifter"
    assert default["USER"] == "postgres"
    assert default["PASSWORD"] == "postgres"
    assert default["HOST"] == "localhost"
    assert default["PORT"] == "5432"
