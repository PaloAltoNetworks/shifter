"""Tests for config._posture startup logging (#948)."""

from __future__ import annotations

import logging

import pytest

from config._posture import (
    describe_auth_posture,
    describe_database_posture,
    describe_deploy_posture,
    describe_environment_posture,
    log_settings_posture,
)


def test_describe_environment_posture():
    posture = describe_environment_posture({"ENVIRONMENT": "development", "DJANGO_DEBUG": "true", "TESTING": "1"})
    assert posture == {"environment": "development", "debug": True, "testing": True}


def test_describe_auth_posture_defaults_to_oidc():
    assert describe_auth_posture({}) == {"auth_provider": "oidc"}


def test_describe_database_posture_uses_host_only_for_postgres():
    posture = describe_database_posture({"DB_HOST": "db.example.internal", "DB_PORT": "5432", "DB_NAME": "shifter"})
    assert posture["engine"] == "postgresql"
    assert posture["host"] == "db.example.internal"
    assert "password" not in posture


def test_describe_database_posture_does_not_invent_missing_values():
    posture = describe_database_posture({})
    assert posture == {"engine": "postgresql", "host": None, "port": None, "name": None}


def test_describe_database_posture_sqlite_in_tests():
    assert describe_database_posture({"TESTING": "1"})["engine"] == "sqlite"


def test_describe_deploy_posture_remote_by_default():
    assert describe_deploy_posture({}) == {
        "cloud_provider": "aws",
        "local_provisioner": None,
        "deploy_mode": "remote",
    }


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        (
            {"LOCAL_PROVISIONER": "vagrant"},
            {"cloud_provider": "aws", "local_provisioner": "vagrant", "deploy_mode": "vagrant"},
        ),
        (
            {"CLOUD_PROVIDER": "gcp", "LOCAL_PROVISIONER": ""},
            {"cloud_provider": "gcp", "local_provisioner": None, "deploy_mode": "remote"},
        ),
    ],
)
def test_describe_deploy_posture_reports_non_default_branches(env, expected):
    assert describe_deploy_posture(env) == expected


def test_log_settings_posture_does_not_log_secrets(caplog):
    caplog.set_level(logging.INFO)
    test_logger = logging.getLogger("test.posture")
    env = {
        "ENVIRONMENT": "production",
        "AUTH_PROVIDER": "oidc",
        "DB_HOST": "10.0.0.5",
        "DB_PASSWORD": "super-secret",
        "REDIS_PASSWORD": "redis-secret",
    }
    log_settings_posture(env, logger=test_logger)
    combined = caplog.text
    assert "super-secret" not in combined
    assert "redis-secret" not in combined
    assert "settings posture:" in combined
    assert "channel-layer posture:" in combined
