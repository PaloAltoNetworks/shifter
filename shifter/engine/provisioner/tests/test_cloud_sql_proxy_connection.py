"""Provisioner connections use the attached native proxy without minting proofs."""

from unittest.mock import patch

import pytest

from provisioner_db import get_db_connection


@pytest.fixture
def native_env(monkeypatch):
    for name in ("DB_PASSWORD", "CLOUD_REGION", "AWS_REGION", "DB_IAM_AUTH"):
        monkeypatch.delenv(name, raising=False)
    for name, value in {
        "DB_AUTH_MODE": "cloud-sql-proxy",
        "CLOUD_PROVIDER": "gcp",
        "DB_HOST": "127.0.0.1",
        "DB_PORT": "5432",
        "DB_NAME": "shifter",
        "DB_USER": "provisioner@synthetic-project.iam",
    }.items():
        monkeypatch.setenv(name, value)


def test_connections_delegate_authentication_to_the_native_proxy(native_env):
    with patch("psycopg.connect") as connect:
        get_db_connection()
        get_db_connection()
    assert connect.call_count == 2
    assert connect.call_args.kwargs == {
        "host": "127.0.0.1",
        "port": 5432,
        "dbname": "shifter",
        "user": "provisioner@synthetic-project.iam",
        "password": "",
        "sslmode": "disable",
        "connect_timeout": 10,
    }


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("CLOUD_PROVIDER", "aws"),
        ("DB_HOST", "db.internal"),
        ("DB_USER", "provisioner_runtime"),
        ("DB_PASSWORD", "unexpected"),
        ("DB_AUTH_MODE", "unknown"),
    ],
)
def test_mismatched_native_connection_is_rejected_before_connect(native_env, monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with patch("psycopg.connect") as connect, pytest.raises(RuntimeError, match="DB_AUTH_MODE"):
        get_db_connection()
    connect.assert_not_called()
