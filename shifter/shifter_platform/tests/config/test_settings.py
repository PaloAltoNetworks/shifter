"""Tests for Django settings module invariants."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SETTINGS_PATH = Path(__file__).resolve().parents[2] / "config" / "settings.py"


def _load_settings_module(module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, SETTINGS_PATH)
    assert spec is not None
    assert spec.loader is not None

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(module_name, None)
    return module


def test_production_settings_exempt_health_from_ssl_redirect(monkeypatch) -> None:
    monkeypatch.setenv("TESTING", "1")
    monkeypatch.setenv("DJANGO_SECRET_KEY", "shifter-platform-tests-secret-key")
    monkeypatch.setenv("DJANGO_DEBUG", "false")

    settings_module = _load_settings_module("config._settings_production_redirect_test")

    assert settings_module.DEBUG is False
    assert settings_module.SECURE_SSL_REDIRECT is True
    assert settings_module.SECURE_REDIRECT_EXEMPT == [r"^health/?$"]
