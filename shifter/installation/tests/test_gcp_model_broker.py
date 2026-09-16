"""Closed deployment configuration and broker-only projection boundaries."""

from __future__ import annotations

import json

import pytest

from installation.errors import InstallationConfigError
from installation.loader import load_root_config
from installation.render import render_tfvars


def broker_settings():
    return {
        "enabled": True,
        "hostname": "models.example.test",
        "vip": "10.40.0.25",
        "admitted_subnets": ["10.50.1.0/24"],
        "tls_secret_name": "model-broker-tls-v1",
        "control_tls_secret_name": "model-control-tls-v1",
        "trust_configmap_name": "model-access-ca-v1",
        "model_projects": {"models-example": "model-invoke"},
    }


def root_config(broker):
    return {
        "backend": "gcp",
        "deployment": {"name": "shifter", "domain": "shifter.example.test"},
        "secrets": {"django_secret_key": "prompt"},
        "settings": {
            "project_id": "platform-example",
            "dynamic_secret_project_id": "secrets-example",
            "region": "us-central1",
            "model_broker": broker,
        },
    }


def test_enabled_broker_roundtrips_through_canonical_terraform_render(write_config):
    config = load_root_config(write_config(root_config(broker_settings())))
    rendered = render_tfvars(config)
    line = next(line for line in rendered.splitlines() if line.startswith("model_broker = "))
    projected = json.loads(line.partition(" = ")[2])
    assert projected["vip"] == "10.40.0.25"
    assert projected["model_projects"] == {"models-example": "model-invoke"}
    assert projected["global_access"] is False


@pytest.mark.parametrize(
    "field,value",
    [
        ("enabled", "true"),
        ("vip", "0.0.0.0"),  # noqa: S104 - rejected wildcard fixture
        ("vip", "169.254.169.254"),
        ("vip", "10.40.0.0/24"),
        ("hostname", "https://models.example.test/path"),
        ("admitted_subnets", ["0.0.0.0/0"]),
        ("admitted_subnets", ["10.50.1.1/24"]),
        ("admitted_subnets", ["10.40.0.0/24"]),
        ("model_projects", {"platform-example": "model-invoke"}),
        ("model_projects", {"secrets-example": "model-invoke"}),
        ("model_projects", {}),
        ("tls_secret_name", "portal/runtime"),
        ("provider_key", "synthetic-secret-sentinel"),
    ],
)
def test_invalid_broker_intent_is_rejected_before_render(write_config, field, value):
    broker = {**broker_settings(), field: value}
    path = write_config(root_config(broker))
    with pytest.raises(InstallationConfigError):
        load_root_config(path)


def test_disabled_defaults_need_no_identity_or_listener(write_config):
    config = load_root_config(write_config(root_config({})))
    assert config.settings["model_broker"]["enabled"] is False
    assert '"enabled":false' in render_tfvars(config)


def test_broker_projection_validates_output_identity_and_mounts_real_catalog(monkeypatch, write_config):
    from pathlib import Path

    from installation.gcp_model_broker import project_model_broker

    raw = (Path(__file__).resolve().parents[3] / "docs/architecture/model-access/example-policy.v1.json").read_text()
    output = {
        **broker_settings(),
        "global_access": False,
        "region": "us-central1",
        "gsa": "model-broker@platform-example.iam.gserviceaccount.com",
        "model_identities": {"models-example": "model-invoke@models-example.iam.gserviceaccount.com"},
    }
    from installation.render import render_model_access_env

    root = root_config(broker_settings())
    root["settings"]["model_access"] = {"enabled": False, "catalog": json.loads(raw)}
    model_env = render_model_access_env(load_root_config(write_config(root)))
    projected = project_model_broker(output, catalog_json=raw, model_access_env=model_env)
    assert projected["catalog_digest"] == json.loads(raw)["digest"]
    assert json.loads(projected["catalog_json"]) == json.loads(raw)
    with pytest.raises(ValueError):
        project_model_broker(
            {**output, "model_identities": {"models-example": "other@foreign.iam.gserviceaccount.com"}},
            catalog_json=raw,
            model_access_env=model_env,
        )
    with pytest.raises(ValueError):
        project_model_broker(output, catalog_json="{}")
    from installation import gcp_model_broker

    payload_size = len(projected["catalog_json"].encode()) + len(projected["identities_json"].encode())
    monkeypatch.setattr(gcp_model_broker, "MAX_BROKER_CONFIGMAP_PAYLOAD_BYTES", payload_size - 1)
    with pytest.raises(ValueError, match="ConfigMap transport"):
        project_model_broker(output, catalog_json=raw, model_access_env=model_env)


def test_configmap_budget_counts_both_documents_and_utf8_bytes():
    from installation.gcp_model_broker import validate_broker_configmap_payload

    validate_broker_configmap_payload("x" * (96 * 1024 - 2), "{}")
    with pytest.raises(ValueError, match="ConfigMap transport"):
        validate_broker_configmap_payload("x" * (96 * 1024 - 1), "{}")
    with pytest.raises(ValueError, match="ConfigMap transport"):
        validate_broker_configmap_payload("é" * (48 * 1024), "{}")


@pytest.mark.parametrize("mutation", ["disabled", "missing", "region", "project"])
def test_readback_must_match_current_deployment_intent(write_config, mutation):
    from installation.gcp_model_broker import validate_model_broker_readback

    config = load_root_config(write_config(root_config(broker_settings())))
    output = {
        **config.settings["model_broker"],
        "region": "us-central1",
        "gsa": "model-broker@platform-example.iam.gserviceaccount.com",
    }
    if mutation == "disabled":
        config = load_root_config(write_config(root_config({})))
    elif mutation == "missing":
        output = None
    elif mutation == "region":
        output["region"] = "us-east1"
    else:
        output["gsa"] = "model-broker@foreign-example.iam.gserviceaccount.com"
    with pytest.raises(ValueError):
        validate_model_broker_readback(output, config)
