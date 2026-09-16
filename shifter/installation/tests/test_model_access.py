"""Installation publication of the canonical model-access catalog (PLAT-202)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from installation.cli import main
from installation.loader import load_root_config
from installation.model_access import (
    DEFAULT_CATALOG_PATH,
    SETTINGS_KEY,
    compute_catalog_digest,
    validate_settings_block,
)
from installation.render import render_model_access_catalog, render_model_access_env

INSTALLATION_ROOT = Path(__file__).parents[1]
CANONICAL_SOURCE = INSTALLATION_ROOT.parent / "shifter_platform/shared/model_access"


def _catalog() -> dict:
    catalog = {
        "contract_version": "model-access-policy/v1",
        "deployment_id": "11111111-1111-4111-8111-111111111111",
        "enabled": False,
        "profiles": [
            {
                "profile_id": "coding",
                "capabilities": ["messages"],
                "allowed_strategies": ["fixed-v1"],
                "data_regions": ["europe-west4"],
                "limits": {
                    "max_request_seconds": 120,
                    "max_request_bytes": 1000000,
                    "max_input_tokens": 8000,
                    "max_output_tokens": 2000,
                    "max_requests_per_window": 60,
                    "request_window_seconds": 60,
                    "max_spend_micro_units": 5000000,
                    "currency": "USD",
                    "max_concurrent_requests": 2,
                },
            }
        ],
        "quota_pools": [
            {
                "quota_pool_id": "vertex-tokens-eu",
                "provider_adapter_id": "vertex-v1",
                "provider_quota_identity": "project:models-a/region:europe-west4/model:claude",
                "dimension": "input_tokens",
                "unit": "tokens/minute",
                "limit": 1000000,
            }
        ],
        "price_schedules": [
            {
                "price_schedule_id": "vertex-price",
                "currency": "USD",
                "valid_until": "2026-10-01T00:00:00Z",
                "prices": [{"component": "input_tokens", "unit_denominator": 1000000, "price_micro_units": 3000000}],
            }
        ],
        "shards": [
            {
                "shard_id": "vertex-primary",
                "provider_adapter_id": "vertex-v1",
                "compute_target_ref": {"owner": "installation", "reference": "gcp:gce-primary"},
                "model_project_ref": {"owner": "deployment", "reference": "project:models-a"},
                "model_account_ref": {"owner": "deployment", "reference": "billing:models-a"},
                "dynamic_secret_project_ref": {"owner": "deployment", "reference": "project:secrets-a"},
                "broker_workload_identity_ref": {"owner": "deployment", "reference": "gsa:model-broker"},
                "credential_ref": {"owner": "broker", "reference": "impersonate:gsa/model-invoke"},
                "region": "europe-west4",
                "provider_model": "publishers/anthropic/models/claude-sonnet",
                "provider_model_version": "20260901",
                "protocol": "anthropic-messages/2023-06-01",
                "capabilities": ["messages"],
                "billing_components": ["input_tokens"],
                "quota_pool_ids": ["vertex-tokens-eu"],
                "weight": 1,
                "enabled": True,
            }
        ],
        "aliases": [
            {
                "logical_alias": "coding-main",
                "profile_id": "coding",
                "strategy": "fixed-v1",
                "affinity": "per_range",
                "eligible_shard_ids": ["vertex-primary"],
                "price_schedule_id": "vertex-price",
            }
        ],
        "sharing_pools": [],
        "sharing_bindings": [],
    }
    catalog["digest"] = compute_catalog_digest(catalog)
    return catalog


def _with_model_access(base: dict, model_access: dict) -> dict:
    settings = dict(base.get("settings", {}))
    if base["backend"] == "gcp":
        settings = {
            "project_id": "acme-shifter",
            "region": "us-central1",
            "dynamic_secret_project_id": "acme-range-secrets",
            **settings,
        }
    result = {**base, "settings": {**settings, SETTINGS_KEY: model_access}}
    return result


def test_distribution_link_points_to_the_canonical_contract_source():
    link = INSTALLATION_ROOT / "canonical_model_access"
    assert link.is_symlink()
    assert link.resolve() == CANONICAL_SOURCE.resolve()


def test_model_access_is_cross_backend_and_normalized(write_config, aws_config, gcp_config):
    for base in (aws_config, gcp_config):
        config = load_root_config(write_config(_with_model_access(base, {"enabled": False, "catalog": _catalog()})))
        assert config.settings[SETTINGS_KEY]["catalog"]["contract_version"] == "model-access-policy/v1"


def test_installer_uses_canonical_semantic_normalization(write_config, gcp_config):
    catalog = _catalog()
    catalog["profiles"][0]["capabilities"] = ["token-count", "messages"]
    catalog["shards"][0]["capabilities"] = ["messages", "token-count"]
    catalog["digest"] = compute_catalog_digest(catalog)
    catalog["profiles"][0]["capabilities"].reverse()

    config = load_root_config(write_config(_with_model_access(gcp_config, {"enabled": False, "catalog": catalog})))

    normalized = config.settings[SETTINGS_KEY]["catalog"]
    assert normalized["profiles"][0]["capabilities"] == ["messages", "token-count"]
    assert normalized["digest"] == catalog["digest"]


def test_installer_materializes_contract_defaults(write_config, aws_config):
    catalog = _catalog()
    catalog.pop("sharing_pools")
    catalog.pop("sharing_bindings")
    catalog["digest"] = compute_catalog_digest(catalog)

    config = load_root_config(write_config(_with_model_access(aws_config, {"enabled": False, "catalog": catalog})))

    normalized = config.settings[SETTINGS_KEY]["catalog"]
    assert normalized["sharing_pools"] == []
    assert normalized["sharing_bindings"] == []


def test_installer_rejects_schema_valid_cross_reference_errors():
    catalog = _catalog()
    catalog["aliases"][0]["eligible_shard_ids"] = ["missing-shard"]
    catalog["digest"] = compute_catalog_digest({**catalog, "aliases": _catalog()["aliases"]})
    _, issues = validate_settings_block({SETTINGS_KEY: {"enabled": False, "catalog": catalog}})
    assert issues
    assert "missing-shard" not in issues[0].render()


def test_installer_rejects_schema_valid_custom_validator_errors():
    catalog = _catalog()
    catalog["aliases"][0]["eligible_shard_ids"] = ["vertex-primary", "vertex-primary"]
    _, issues = validate_settings_block({SETTINGS_KEY: {"enabled": False, "catalog": catalog}})
    assert issues


def test_enabled_configuration_requires_catalog():
    _, issues = validate_settings_block({SETTINGS_KEY: {"enabled": True}})
    assert issues
    assert issues[0].path.startswith("settings.model_access")


def test_generated_schema_rejects_unknown_catalog_members():
    catalog = _catalog()
    catalog["credential_value"] = "must-never-be-a-field"
    _, issues = validate_settings_block({SETTINGS_KEY: {"enabled": False, "catalog": catalog}})
    assert issues
    assert "must-never-be-a-field" not in "\n".join(issue.render() for issue in issues)


@pytest.mark.parametrize("unsafe", [True, 1.5, "100"])
def test_generated_schema_rejects_non_integer_limit_coercion(unsafe):
    catalog = _catalog()
    catalog["profiles"][0]["limits"]["max_request_seconds"] = unsafe
    _, issues = validate_settings_block({SETTINGS_KEY: {"enabled": False, "catalog": catalog}})
    assert issues


def test_renderer_writes_catalog_artifact_separately_from_environment(write_config, gcp_config):
    config = load_root_config(write_config(_with_model_access(gcp_config, {"enabled": False, "catalog": _catalog()})))
    artifact = render_model_access_catalog(config)
    env = render_model_access_env(config)
    assert json.loads(artifact)["contract_version"] == "model-access-policy/v1"
    assert "MODEL_ACCESS_ENABLED=false" in env
    assert f"MODEL_ACCESS_CATALOG_PATH={DEFAULT_CATALOG_PATH}" in env
    assert "MODEL_ACCESS_CATALOG_DIGEST=sha256:" in env
    assert "vertex-primary" not in env


def test_absent_configuration_stays_disabled_and_has_no_catalog_path(write_config, aws_config):
    config = load_root_config(write_config(aws_config))
    assert render_model_access_catalog(config) == ""
    env = render_model_access_env(config)
    assert env == "MODEL_ACCESS_ENABLED=false\nMODEL_ACCESS_CATALOG_PATH=\nMODEL_ACCESS_CATALOG_DIGEST=\n"


def test_cli_renders_separate_catalog_and_environment(write_config, gcp_config, tmp_path):
    config_path = write_config(_with_model_access(gcp_config, {"enabled": False, "catalog": _catalog()}))
    catalog_path = tmp_path / "catalog.json"
    env_path = tmp_path / "model-access.env"
    assert main(["render-model-access-catalog", str(config_path), "--output", str(catalog_path)]) == 0
    assert main(["render-model-access-env", str(config_path), "--output", str(env_path)]) == 0
    assert json.loads(catalog_path.read_text())["digest"] == _catalog()["digest"]
    assert "vertex-primary" not in env_path.read_text()
