"""Tests for the RDS IAM PostgreSQL backend (issue #159).

The backend mints a short-lived RDS IAM auth token per connection and uses it
as the password, so the running portal holds no long-lived database password.
"""

from __future__ import annotations

import pytest
from django.core.exceptions import ImproperlyConfigured

from config.db_backends.rds_iam import base


@pytest.fixture
def settings_dict():
    return {
        "ENGINE": "config.db_backends.rds_iam",
        "NAME": "shifter",
        "USER": "portal_runtime",
        "PASSWORD": "",
        "HOST": "db.example.internal",
        "PORT": "5432",
        "OPTIONS": {"connect_timeout": 10, "sslmode": "require"},
        "CONN_MAX_AGE": 0,
        "AUTOCOMMIT": True,
        "TIME_ZONE": None,
    }


def _wrapper(settings_dict):
    return base.DatabaseWrapper(settings_dict, alias="default")


def test_generate_iam_auth_token_calls_boto3(monkeypatch):
    captured = {}

    class FakeClient:
        def generate_db_auth_token(self, **kwargs):
            captured.update(kwargs)
            return "iam-token-value"

    monkeypatch.setattr(base, "_rds_client", lambda region: FakeClient())

    token = base.generate_iam_auth_token("h", 5432, "u", "us-east-2")

    assert token == "iam-token-value"
    assert captured == {
        "DBHostname": "h",
        "Port": 5432,
        "DBUsername": "u",
        "Region": "us-east-2",
    }


def test_get_connection_params_injects_token(monkeypatch, settings_dict):
    monkeypatch.setenv("AWS_REGION", "us-east-2")
    monkeypatch.setattr(
        base, "generate_iam_auth_token", lambda host, port, user, region: f"tok:{user}@{host}:{port}/{region}"
    )

    params = _wrapper(settings_dict).get_connection_params()

    assert params["password"] == "tok:portal_runtime@db.example.internal:5432/us-east-2"
    assert params["host"] == "db.example.internal"
    assert params["user"] == "portal_runtime"
    # SSL option from settings flows through unchanged.
    assert params["sslmode"] == "require"


def test_region_prefers_db_iam_region(monkeypatch):
    monkeypatch.setenv("AWS_REGION", "us-east-2")
    monkeypatch.setenv("DB_IAM_REGION", "eu-west-1")
    assert base._resolve_region() == "eu-west-1"


def test_region_falls_back_to_aws_region(monkeypatch):
    monkeypatch.delenv("DB_IAM_REGION", raising=False)
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    monkeypatch.setenv("AWS_REGION", "ap-southeast-2")
    assert base._resolve_region() == "ap-southeast-2"


def test_region_falls_back_to_aws_default_region(monkeypatch):
    # AWS_DEFAULT_REGION is the SDK's canonical variable; it must resolve as the
    # sole source when DB_IAM_REGION and AWS_REGION are both unset.
    monkeypatch.delenv("DB_IAM_REGION", raising=False)
    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-central-1")
    assert base._resolve_region() == "eu-central-1"


def test_region_missing_is_fail_loud(monkeypatch):
    for var in ("DB_IAM_REGION", "AWS_REGION", "AWS_DEFAULT_REGION"):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(ImproperlyConfigured, match="region"):
        base._resolve_region()


def test_missing_user_is_fail_loud(monkeypatch, settings_dict):
    monkeypatch.setenv("AWS_REGION", "us-east-2")
    settings_dict["USER"] = ""
    with pytest.raises(ImproperlyConfigured, match="DB_HOST and DB_USER"):
        _wrapper(settings_dict).get_connection_params()


def test_missing_host_is_fail_loud(monkeypatch, settings_dict):
    # The guard is `not host or not user`; exercise the host branch so dropping
    # the host check cannot pass silently.
    monkeypatch.setenv("AWS_REGION", "us-east-2")
    settings_dict["HOST"] = ""
    with pytest.raises(ImproperlyConfigured, match="DB_HOST and DB_USER"):
        _wrapper(settings_dict).get_connection_params()
