"""Fail-closed composition-root tests for Mission Control lease settings (issue #27)."""

from __future__ import annotations

import importlib
import json
import os

import pytest
from django.core.exceptions import ImproperlyConfigured

MODULE = "config._mission_control_lease_settings"
ENV_KEY = "MISSION_CONTROL_LEASE_POLICY_JSON"


def _reload(monkeypatch, value: str | None = None):
    monkeypatch.delenv(ENV_KEY, raising=False)
    if value is not None:
        monkeypatch.setenv(ENV_KEY, value)
    return importlib.reload(importlib.import_module(MODULE))


@pytest.fixture(autouse=True)
def _restore_module():
    yield
    os.environ.pop(ENV_KEY, None)
    importlib.reload(importlib.import_module(MODULE))


def test_absent_policy_uses_canonical_defaults(monkeypatch) -> None:
    policy = _reload(monkeypatch).MISSION_CONTROL_LEASE_POLICY
    assert (policy.initial_days, policy.extension_days, policy.maximum_days) == (30, 30, 365)
    assert policy.extensions_enabled is True


@pytest.mark.parametrize("value", ["", "   "])
def test_present_but_blank_policy_fails_startup(monkeypatch, value: str) -> None:
    # A set-but-blank variable is a broken deployment substitution, not an omission.
    with pytest.raises(ImproperlyConfigured, match="MISSION_CONTROL_LEASE_POLICY_JSON"):
        _reload(monkeypatch, value)


def test_custom_policy_binds(monkeypatch) -> None:
    value = json.dumps({"initial_days": 7, "extension_days": 3, "maximum_days": 90, "extensions_enabled": False})
    policy = _reload(monkeypatch, value).MISSION_CONTROL_LEASE_POLICY
    assert (policy.initial_days, policy.extension_days, policy.maximum_days) == (7, 3, 90)
    assert policy.extensions_enabled is False


@pytest.mark.parametrize(
    "value",
    [
        "{not json",
        json.dumps({"initial_days": 0}),
        json.dumps({"initial_days": 100, "maximum_days": 30}),
        json.dumps({"bogus": 1}),
        json.dumps([1, 2, 3]),
    ],
)
def test_invalid_policy_fails_startup(monkeypatch, value: str) -> None:
    with pytest.raises(ImproperlyConfigured, match="MISSION_CONTROL_LEASE_POLICY_JSON"):
        _reload(monkeypatch, value)
