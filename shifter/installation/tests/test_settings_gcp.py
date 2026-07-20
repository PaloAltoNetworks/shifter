"""Tests for the closed GCP backend settings model (``installation.settings_gcp``)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from installation.settings_gcp import GcpBackendSettings


class TestGcpBackendSettings:
    def test_minimal_valid_settings(self):
        settings = GcpBackendSettings.model_validate({"project_id": "acme-shifter", "region": "us-central1"})
        assert settings.project_id == "acme-shifter"
        assert settings.region == "us-central1"

    def test_model_is_closed_and_rejects_unknown_settings(self):
        # extra='forbid' — an unknown GCP setting fails before any infrastructure mutation.
        with pytest.raises(ValidationError):
            GcpBackendSettings.model_validate({"project_id": "acme-shifter", "region": "us-central1", "bogus": "value"})

    def test_range_egress_is_not_a_model_field(self):
        # range_egress is a shared cross-backend key validated by the loader, not the model
        # (mirrors AwsSettings); the closed model rejects it as an unknown key.
        assert "range_egress" not in GcpBackendSettings.model_fields
        with pytest.raises(ValidationError):
            GcpBackendSettings.model_validate(
                {"project_id": "acme-shifter", "region": "us-central1", "range_egress": {"mode": "status-quo"}}
            )

    def test_project_id_is_required(self):
        with pytest.raises(ValidationError):
            GcpBackendSettings.model_validate({"region": "us-central1"})

    def test_region_is_required(self):
        with pytest.raises(ValidationError):
            GcpBackendSettings.model_validate({"project_id": "acme-shifter"})

    @pytest.mark.parametrize(
        "project_id",
        [
            "acme",  # too short (< 6)
            "ACME-shifter",  # uppercase
            "acme_shifter",  # underscore
            "1acme-shifter",  # leading digit
            "acme-shifter-",  # trailing hyphen
            "a" * 31,  # too long (> 30)
        ],
    )
    def test_invalid_project_id_is_rejected(self, project_id):
        with pytest.raises(ValidationError):
            GcpBackendSettings.model_validate({"project_id": project_id, "region": "us-central1"})

    @pytest.mark.parametrize("project_id", ["acme-shifter", "your-gcp-project", "shifter", "abc123-def"])
    def test_valid_project_id_is_accepted(self, project_id):
        settings = GcpBackendSettings.model_validate({"project_id": project_id, "region": "us-central1"})
        assert settings.project_id == project_id

    @pytest.mark.parametrize("region", ["", "US-Central1", "us central1", "-us-central1"])
    def test_invalid_region_is_rejected(self, region):
        with pytest.raises(ValidationError):
            GcpBackendSettings.model_validate({"project_id": "acme-shifter", "region": region})

    @pytest.mark.parametrize("region", ["us-central1", "europe-west4", "asia-northeast1"])
    def test_valid_region_is_accepted(self, region):
        settings = GcpBackendSettings.model_validate({"project_id": "acme-shifter", "region": region})
        assert settings.region == region


class TestGcpBundleIntegration:
    """The gcp registry entry uses the closed model, and the loader enforces it end to end.

    (Deeper loader coverage — range_egress ownership, secret-reference grammar — lives in
    ``test_loader.py`` alongside the AWS equivalents.)"""

    def test_registry_gcp_bundle_uses_the_closed_settings_model(self):
        from installation.registry import get_backend_bundle

        assert get_backend_bundle("gcp").settings_model is GcpBackendSettings

    def _gcp_config(self, settings: dict) -> dict:
        return {
            "backend": "gcp",
            "deployment": {"name": "shifter", "domain": "shifter.example.com"},
            "secrets": {"django_secret_key": "prompt"},
            "settings": settings,
        }

    def test_loader_accepts_valid_gcp_settings(self, write_config):
        from installation.loader import load_root_config

        cfg = load_root_config(write_config(self._gcp_config({"project_id": "acme-shifter", "region": "us-central1"})))
        assert cfg.settings["project_id"] == "acme-shifter"
        assert cfg.settings["region"] == "us-central1"

    def test_loader_rejects_unknown_gcp_setting_fail_closed(self, write_config):
        from installation.errors import InstallationConfigError
        from installation.loader import load_root_config

        # Only load_root_config should raise inside the pytest.raises block; build the
        # config file first (SonarCloud python:S5915).
        config_path = write_config(
            self._gcp_config({"project_id": "acme-shifter", "region": "us-central1", "bogus": "x"})
        )
        with pytest.raises(InstallationConfigError) as excinfo:
            load_root_config(config_path)
        assert any(issue.path == "settings.bogus" for issue in excinfo.value.issues)

    def test_loader_rejects_gcp_settings_missing_project_id(self, write_config):
        from installation.loader import validate_root_config_file

        issues = validate_root_config_file(write_config(self._gcp_config({"region": "us-central1"})))
        assert any(issue.path == "settings.project_id" for issue in issues)
