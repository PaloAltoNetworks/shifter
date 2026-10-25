"""Tests for the closed GCP backend settings model (``installation.settings_gcp``)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from installation.settings_gcp import GcpBackendSettings


def _settings(**overrides: object) -> dict[str, object]:
    return {
        "project_id": "acme-shifter",
        "dynamic_secret_project_id": "acme-range-secrets",
        "region": "us-central1",
        **overrides,
    }


class TestGcpBackendSettings:
    def test_native_sql_and_policy_settings_are_closed_operator_intent(self):
        settings = GcpBackendSettings.model_validate(
            _settings(
                cloud_sql_iam_auth=True,
                openfga={
                    "enabled": True,
                    "store_id": "01J00000000000000000000001",
                    "model_id": "01J00000000000000000000000",
                    "runtime_secret_ref": "projects/acme-shifter/secrets/policy-runtime",
                    "admin_secret_ref": "projects/acme-shifter/secrets/policy-admin",
                    "ca_secret_ref": "projects/acme-shifter/secrets/policy-ca",
                },
            )
        )
        assert settings.cloud_sql_iam_auth is True
        assert settings.openfga.enabled is True
        for bad in (
            {"arbitrary_proxy_args": ["--impersonate-service-account=operator"]},
            {"runtime_secret_ref": "secret-payload"},
        ):
            with pytest.raises(ValidationError):
                GcpBackendSettings.model_validate(_settings(cloud_sql_iam_auth=True, openfga=bad))

    def test_policy_requires_complete_native_configuration_and_separate_admin_credentials(self):
        policy = {
            "enabled": True,
            "store_id": "01J00000000000000000000001",
            "model_id": "01J00000000000000000000000",
            "runtime_secret_ref": "projects/acme-shifter/secrets/policy-runtime",
            "admin_secret_ref": "projects/acme-shifter/secrets/policy-runtime",
            "ca_secret_ref": "projects/acme-shifter/secrets/policy-ca",
        }
        with pytest.raises(ValidationError):
            GcpBackendSettings.model_validate(_settings(cloud_sql_iam_auth=True, openfga=policy))
        policy["admin_secret_ref"] = "projects/acme-shifter/secrets/policy-admin"
        with pytest.raises(ValidationError):
            GcpBackendSettings.model_validate(_settings(cloud_sql_iam_auth=False, openfga=policy))

    def test_minimal_valid_settings(self):
        settings = GcpBackendSettings.model_validate(_settings())
        assert settings.project_id == "acme-shifter"
        assert settings.range_resource_project_id == "acme-range-secrets"
        assert settings.region == "us-central1"
        assert settings.provisioner_static_resource_refs == {}

    def test_normalized_dump_preserves_external_contract_aliases(self):
        normalized = GcpBackendSettings.model_validate(_settings()).model_dump()

        assert normalized["dynamic_secret_project_id"] == "acme-range-secrets"
        assert normalized["provisioner_static_secret_refs"] == {}
        assert "range_resource_project_id" not in normalized
        assert "provisioner_static_resource_refs" not in normalized

    def test_rebuild_from_root_settings_ignores_shared_policy_blocks(self):
        settings = {**_settings(), "range_egress": {"mode": "status-quo"}}

        rebuilt = GcpBackendSettings.from_root_settings(settings)

        assert rebuilt.range_resource_project_id == "acme-range-secrets"

    def test_static_secret_refs_are_closed_full_resource_names(self):
        settings = GcpBackendSettings.model_validate(
            _settings(
                provisioner_static_secret_refs={
                    "GDC_ACCESS_SECRET_ID": "projects/acme-shifter/secrets/shifter-prod-gdc-access",
                    "GDC_VM_IMAGE_GCS_SECRET_ID": "projects/image-project/secrets/image-key",
                }
            )
        )
        assert set(settings.provisioner_static_resource_refs) == {
            "GDC_ACCESS_SECRET_ID",
            "GDC_VM_IMAGE_GCS_SECRET_ID",
        }

        unknown_secret = _settings(
            provisioner_static_secret_refs={"ARBITRARY_SECRET": "projects/acme-shifter/secrets/x"}
        )
        with pytest.raises(ValidationError):
            GcpBackendSettings.model_validate(unknown_secret)
        short_secret_ref = _settings(provisioner_static_secret_refs={"GDC_ACCESS_SECRET_ID": "shifter-prod-gdc-access"})
        with pytest.raises(ValidationError):
            GcpBackendSettings.model_validate(short_secret_ref)

    def test_model_is_closed_and_rejects_unknown_settings(self):
        # extra='forbid' — an unknown GCP setting fails before any infrastructure mutation.
        unknown_setting = _settings(bogus="value")
        with pytest.raises(ValidationError):
            GcpBackendSettings.model_validate(unknown_setting)

    def test_range_egress_is_not_a_model_field(self):
        # range_egress is a shared cross-backend key validated by the loader, not the model
        # (mirrors AwsSettings); the closed model rejects it as an unknown key.
        assert "range_egress" not in GcpBackendSettings.model_fields
        misplaced_setting = _settings(range_egress={"mode": "status-quo"})
        with pytest.raises(ValidationError):
            GcpBackendSettings.model_validate(misplaced_setting)

    def test_project_id_is_required(self):
        with pytest.raises(ValidationError):
            GcpBackendSettings.model_validate(
                {"dynamic_secret_project_id": "acme-range-secrets", "region": "us-central1"}
            )

    def test_dynamic_secret_project_id_is_required(self):
        with pytest.raises(ValidationError):
            GcpBackendSettings.model_validate({"project_id": "acme-shifter", "region": "us-central1"})

    def test_region_is_required(self):
        with pytest.raises(ValidationError):
            GcpBackendSettings.model_validate(
                {"project_id": "acme-shifter", "dynamic_secret_project_id": "acme-range-secrets"}
            )

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
        invalid_settings = _settings(project_id=project_id)
        with pytest.raises(ValidationError):
            GcpBackendSettings.model_validate(invalid_settings)

    @pytest.mark.parametrize("project_id", ["acme-shifter", "your-gcp-project", "shifter", "abc123-def"])
    def test_valid_project_id_is_accepted(self, project_id):
        settings = GcpBackendSettings.model_validate(_settings(project_id=project_id))
        assert settings.project_id == project_id

    @pytest.mark.parametrize("region", ["", "US-Central1", "us central1", "-us-central1"])
    def test_invalid_region_is_rejected(self, region):
        invalid_settings = _settings(region=region)
        with pytest.raises(ValidationError):
            GcpBackendSettings.model_validate(invalid_settings)

    @pytest.mark.parametrize("region", ["us-central1", "europe-west4", "asia-northeast1"])
    def test_valid_region_is_accepted(self, region):
        settings = GcpBackendSettings.model_validate(_settings(region=region))
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

        cfg = load_root_config(write_config(self._gcp_config(_settings())))
        assert cfg.settings["project_id"] == "acme-shifter"
        assert cfg.settings["region"] == "us-central1"

    def test_loader_rejects_unknown_gcp_setting_fail_closed(self, write_config):
        from installation.errors import InstallationConfigError
        from installation.loader import load_root_config

        # Only load_root_config should raise inside the pytest.raises block; build the
        # config file first (SonarCloud python:S5915).
        config_path = write_config(self._gcp_config(_settings(bogus="x")))
        with pytest.raises(InstallationConfigError) as excinfo:
            load_root_config(config_path)
        assert any(issue.path == "settings.bogus" for issue in excinfo.value.issues)

    def test_loader_accepts_range_telemetry_overrides(self, write_config):
        from installation.loader import load_root_config

        telemetry = {
            "vpc_flow_logs": {"flow_sampling": 0.25, "aggregation_interval": "INTERVAL_1_MIN"},
            "nat_logs": {"filter": "ERRORS_ONLY"},
            "vertex_data_access_logs": {"enabled": False},
        }
        cfg = load_root_config(write_config(self._gcp_config(_settings(range_telemetry=telemetry))))

        settings = GcpBackendSettings.from_root_settings(cfg.settings)
        assert settings.range_telemetry.vpc_flow_logs.flow_sampling == 0.25
        assert settings.range_telemetry.nat_logs.filter == "ERRORS_ONLY"
        assert settings.range_telemetry.vertex_data_access_logs.enabled is False

    def test_range_telemetry_defaults_on_when_block_is_absent(self, write_config):
        from installation.loader import load_root_config

        cfg = load_root_config(write_config(self._gcp_config(_settings())))

        telemetry = GcpBackendSettings.from_root_settings(cfg.settings).range_telemetry
        assert telemetry.vpc_flow_logs.enabled is True
        assert telemetry.nat_logs.enabled is True
        assert telemetry.vertex_data_access_logs.enabled is True

    @pytest.mark.parametrize(
        ("telemetry", "path"),
        [
            ({"vpc_flow_logs": {"enabled": "no"}}, "settings.range_telemetry.vpc_flow_logs.enabled"),
            ({"vpc_flow_logs": {"flow_sampling": 0}}, "settings.range_telemetry.vpc_flow_logs.flow_sampling"),
            ({"nat_logs": {"filter": "SOME"}}, "settings.range_telemetry.nat_logs.filter"),
            ({"audit": {}}, "settings.range_telemetry.audit"),
        ],
    )
    def test_loader_rejects_invalid_range_telemetry(self, write_config, telemetry, path):
        from installation.errors import InstallationConfigError
        from installation.loader import load_root_config

        config_path = write_config(self._gcp_config(_settings(range_telemetry=telemetry)))
        with pytest.raises(InstallationConfigError) as excinfo:
            load_root_config(config_path)
        assert any(issue.path == path for issue in excinfo.value.issues)

    def test_loader_rejects_gcp_settings_missing_project_id(self, write_config):
        from installation.loader import validate_root_config_file

        issues = validate_root_config_file(write_config(self._gcp_config({"region": "us-central1"})))
        assert any(issue.path == "settings.project_id" for issue in issues)
