from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
import yaml

MODULE_PATH = Path(__file__).resolve().parents[1] / "apply_shifter_config_overlay.py"
SPEC = importlib.util.spec_from_file_location("apply_shifter_config_overlay", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
ConfigOverlayError = MODULE.ConfigOverlayError
apply_overlay = MODULE.apply_overlay


def _config(tmp_path: Path) -> Path:
    path = tmp_path / "shifter.yaml"
    path.write_text(
        "backend: gcp\n"
        "secrets:\n"
        "  django_secret_key: retained-secret\n"
        "settings:\n"
        "  project_id: platform-example\n"
        "  model_access:\n"
        "    enabled: false\n",
        encoding="utf-8",
    )
    path.chmod(0o600)
    return path


def test_overlay_replaces_only_allowed_settings_and_preserves_mode(tmp_path):
    path = _config(tmp_path)
    overlay = {
        "settings": {
            "model_access": {"enabled": True, "catalog": {"contract_version": "model-access-policy/v3"}},
            "model_broker": {"enabled": True},
            "model_broker_runtime": {"fingerprint_secret_name": "broker-fingerprint-v1"},
        }
    }

    assert apply_overlay(path, json.dumps(overlay)) is True

    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert value["settings"]["project_id"] == "platform-example"
    assert value["settings"]["model_access"]["enabled"] is True
    assert value["secrets"]["django_secret_key"] == "retained-secret"
    assert path.stat().st_mode & 0o777 == 0o600


def test_empty_overlay_leaves_config_byte_identical(tmp_path):
    path = _config(tmp_path)
    before = path.read_bytes()

    assert apply_overlay(path, "") is False

    assert path.read_bytes() == before


def test_reviewed_overlay_file_takes_precedence_over_environment_value(tmp_path, monkeypatch):
    path = _config(tmp_path)
    overlay = tmp_path / "overlay.json"
    overlay.write_text(json.dumps({"settings": {"model_access": {"enabled": True}}}), encoding="utf-8")
    monkeypatch.setenv("SHIFTER_CONFIG_OVERLAY_FILE", str(overlay))
    monkeypatch.setenv("SHIFTER_CONFIG_OVERLAY_JSON", '{"settings":{"model_access":{"enabled":false}}}')
    monkeypatch.setattr("sys.argv", ["apply_shifter_config_overlay.py", "--config", str(path)])

    assert MODULE.main() == 0
    assert yaml.safe_load(path.read_text(encoding="utf-8"))["settings"]["model_access"]["enabled"] is True


@pytest.mark.parametrize(
    "overlay",
    [
        "[]",
        '{"settings":{}}',
        '{"settings":{"project_id":"other-project"}}',
        '{"secrets":{"django_secret_key":"replacement"}}',
        '{"settings":{"model_access":{}},"settings":{"model_broker":{}}}',
    ],
)
def test_overlay_rejects_open_or_ambiguous_input(tmp_path, overlay):
    path = _config(tmp_path)
    before = path.read_bytes()

    with pytest.raises(ConfigOverlayError):
        apply_overlay(path, overlay)

    assert path.read_bytes() == before
