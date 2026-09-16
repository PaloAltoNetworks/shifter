"""Tests for ``installation.mission_control_lease`` + loader/render wiring (issue #27).

The Mission Control lease policy is validated at the installation boundary so AWS
and GCP share one source of truth, then published to the runtime as a single
``MISSION_CONTROL_LEASE_POLICY_JSON`` env line. These tests pin the adapter's
validation, the loader's strip/normalize behavior, and the render bridge.
"""

from __future__ import annotations

import json

import pytest

from installation.errors import InstallationConfigError
from installation.loader import load_root_config
from installation.mission_control_lease import SETTINGS_KEY, validate_settings_block
from installation.render import render_mission_control_lease_env

CANONICAL_DEFAULTS = {
    "initial_days": 30,
    "extension_days": 30,
    "maximum_days": 365,
    "extensions_enabled": True,
}


class TestValidateSettingsBlock:
    def test_absent_block_is_unchanged(self):
        settings = {"region": "us-east-2"}
        normalized, issues = validate_settings_block(settings)
        assert issues == []
        assert normalized == settings
        assert SETTINGS_KEY not in normalized

    def test_valid_block_normalizes(self):
        settings = {
            SETTINGS_KEY: {"initial_days": 7, "extension_days": 3, "maximum_days": 90, "extensions_enabled": False}
        }
        normalized, issues = validate_settings_block(settings)
        assert issues == []
        assert normalized[SETTINGS_KEY] == {
            "initial_days": 7,
            "extension_days": 3,
            "maximum_days": 90,
            "extensions_enabled": False,
        }

    def test_partial_block_fills_canonical_defaults(self):
        normalized, issues = validate_settings_block({SETTINGS_KEY: {"initial_days": 10}})
        assert issues == []
        assert normalized[SETTINGS_KEY] == {**CANONICAL_DEFAULTS, "initial_days": 10}

    def test_initial_gt_maximum_yields_anchored_issue(self):
        _, issues = validate_settings_block({SETTINGS_KEY: {"initial_days": 100, "maximum_days": 30}})
        assert issues
        assert all(issue.path.startswith(f"settings.{SETTINGS_KEY}") for issue in issues)

    def test_non_mapping_block_yields_issue(self):
        _, issues = validate_settings_block({SETTINGS_KEY: [1, 2, 3]})
        assert issues
        assert issues[0].path == f"settings.{SETTINGS_KEY}"

    def test_absent_key_is_omission_not_error(self):
        normalized, issues = validate_settings_block({"region": "us-east-2"})
        assert issues == []
        assert SETTINGS_KEY not in normalized

    def test_explicit_null_block_is_rejected(self):
        # `mission_control_leases:` with no value is a broken declaration, not an omission.
        _, issues = validate_settings_block({SETTINGS_KEY: None})
        assert issues
        assert issues[0].path == f"settings.{SETTINGS_KEY}"
        assert "null" in issues[0].message

    def test_unknown_field_yields_issue(self):
        _, issues = validate_settings_block({SETTINGS_KEY: {"bogus": 1}})
        assert issues
        assert any("bogus" in issue.path or "bogus" in issue.message for issue in issues)


# The GCP closed settings model requires these keys; a loadable config carries them.
_GCP_REQUIRED_SETTINGS = {
    "region": "us-central1",
    "project_id": "acme-shifter",
    "dynamic_secret_project_id": "acme-range-secrets",
}


def _with_leases(gcp_config: dict, block: dict | None = None) -> dict:
    settings = {**_GCP_REQUIRED_SETTINGS, **gcp_config.get("settings", {})}
    if block is not None:
        settings[SETTINGS_KEY] = block
    gcp_config["settings"] = settings
    return gcp_config


class TestLoaderIntegration:
    def test_valid_policy_normalized_on_config(self, gcp_config, write_config):
        config = load_root_config(write_config(_with_leases(gcp_config, {"initial_days": 7, "maximum_days": 90})))
        assert config.settings[SETTINGS_KEY] == {**CANONICAL_DEFAULTS, "initial_days": 7, "maximum_days": 90}

    def test_invalid_policy_raises_aggregated(self, gcp_config, write_config):
        cfg_path = write_config(_with_leases(gcp_config, {"initial_days": 100, "maximum_days": 30}))
        with pytest.raises(InstallationConfigError) as exc:
            load_root_config(cfg_path)
        assert any(SETTINGS_KEY in issue.path for issue in exc.value.issues)

    def test_absent_block_stays_absent(self, gcp_config, write_config):
        config = load_root_config(write_config(_with_leases(gcp_config)))
        assert SETTINGS_KEY not in config.settings

    def test_aggregated_errors_include_lease_issue_when_root_schema_fails(self, write_config):
        # Root schema fails (invalid deployment name) but the backend still resolves, so
        # the aggregated report also surfaces the invalid lease block in one pass.
        config = {
            "backend": "gcp",
            "deployment": {"name": "Bad Name", "domain": "localhost"},
            "secrets": {"django_secret_key": "prompt"},
            "settings": {**_GCP_REQUIRED_SETTINGS, SETTINGS_KEY: {"initial_days": 100, "maximum_days": 30}},
        }
        cfg_path = write_config(config)
        with pytest.raises(InstallationConfigError) as exc:
            load_root_config(cfg_path)
        paths = [issue.path for issue in exc.value.issues]
        assert any("deployment.name" in path for path in paths)
        assert any(SETTINGS_KEY in path for path in paths)

    def test_aws_backend_normalizes_the_same_block(self, aws_config, write_config):
        # Cross-backend parity: the AWS closed-settings model must strip and preserve the
        # shared lease block identically to GCP (the block is not an AWS-owned key).
        aws_config["settings"][SETTINGS_KEY] = {"initial_days": 7, "maximum_days": 90}
        config = load_root_config(write_config(aws_config))
        assert config.settings[SETTINGS_KEY] == {**CANONICAL_DEFAULTS, "initial_days": 7, "maximum_days": 90}


class TestRender:
    def _payload(self, line: str) -> dict:
        env_line = next(row for row in line.splitlines() if row.startswith("MISSION_CONTROL_LEASE_POLICY_JSON="))
        return json.loads(env_line.split("=", 1)[1])

    def test_absent_block_renders_defaults(self, gcp_config, write_config):
        config = load_root_config(write_config(_with_leases(gcp_config)))
        assert self._payload(render_mission_control_lease_env(config)) == CANONICAL_DEFAULTS

    def test_custom_block_rendered(self, gcp_config, write_config):
        block = {"initial_days": 7, "extension_days": 3, "maximum_days": 90, "extensions_enabled": False}
        config = load_root_config(write_config(_with_leases(gcp_config, block)))
        assert self._payload(render_mission_control_lease_env(config)) == block

    def test_aws_custom_block_rendered(self, aws_config, write_config):
        block = {"initial_days": 7, "extension_days": 3, "maximum_days": 90, "extensions_enabled": False}
        aws_config["settings"][SETTINGS_KEY] = block
        config = load_root_config(write_config(aws_config))
        assert self._payload(render_mission_control_lease_env(config)) == block

    def test_render_line_is_single_kv_parseable(self, gcp_config, write_config):
        # The AWS/GCP producers split each line on "=", so the render must emit exactly
        # one KEY=VALUE line with no header comment.
        config = load_root_config(write_config(_with_leases(gcp_config)))
        rows = [row for row in render_mission_control_lease_env(config).splitlines() if row.strip()]
        assert len(rows) == 1
        key, value = rows[0].split("=", 1)
        assert key == "MISSION_CONTROL_LEASE_POLICY_JSON"
        assert json.loads(value) == CANONICAL_DEFAULTS
