"""Activation rejects incomplete provider and accounting configuration."""

import json
from pathlib import Path

import pytest
from shared.model_access import seal_catalog

from installation.model_broker_runtime import project_broker_runtime


@pytest.fixture
def active_runtime():
    catalog = json.loads(
        (Path(__file__).resolve().parents[3] / "docs/architecture/model-access/example-policy.v3.json").read_text()
    )
    catalog.pop("digest")
    catalog["enabled"] = True
    target = {
        "shard_id": "vertex-primary",
        "provider": "vertex-v1",
        "region": "europe-west4",
        "count_region": "eu",
        "model": "publishers/anthropic/models/claude-sonnet",
        "credential_reference": "impersonate:gsa/model-invoke",
        "principal": "model-invoke@models-example.iam.gserviceaccount.com",
        "project": "models-example",
        "context_window_tokens": 200000,
    }
    settings = {
        "provider_inventory": {"contract_version": "model-broker-providers/v1", "targets": [target]},
        "fingerprint_secret_name": "broker-fingerprint-v1",
        "fingerprint_key_version": "v1",
    }
    return settings, catalog


def project(settings, catalog, **overrides):
    return project_broker_runtime(
        settings,
        catalog_json=seal_catalog(catalog).model_dump_json(),
        provider=overrides.get("provider", "gcp"),
        model_identities=overrides.get(
            "model_identities", {"models-example": "model-invoke@models-example.iam.gserviceaccount.com"}
        ),
    )


def test_projects_nonsecret_inventory_and_versioned_secret_reference(active_runtime):
    settings, catalog = active_runtime
    projected = project(settings, catalog)
    assert json.loads(projected["providers_json"]) == settings["provider_inventory"]
    assert projected["fingerprint_secret_name"] == "broker-fingerprint-v1"


# Invalid synthetic key envelope: decoded content is just "abc", not key material.
_KEY_LABEL = "PRIVATE KEY"


@pytest.mark.parametrize("material", [f"-----BEGIN {_KEY_LABEL}-----\nYWJj\n-----END {_KEY_LABEL}-----", "not a CA"])
def test_guest_trust_refuses_nonpublic_certificate_material(active_runtime, material):
    settings, catalog = active_runtime
    settings["guest_trust_ca_pem"] = material
    with pytest.raises(ValueError):
        project(settings, catalog)


@pytest.mark.parametrize("fault", ["identity", "shard", "model", "key", "count_price", "disabled", "cloud"])
def test_rejects_execution_config_that_cannot_enforce_catalog(active_runtime, fault):
    settings, catalog = active_runtime
    overrides = {}
    if fault == "identity":
        overrides["model_identities"] = {"models-example": "different@models-example.iam.gserviceaccount.com"}
    elif fault in {"shard", "model"}:
        settings["provider_inventory"]["targets"][0]["shard_id" if fault == "shard" else "model"] = (
            "unbound-shard" if fault == "shard" else "publishers/anthropic/models/different-model"
        )
    elif fault == "key":
        settings["fingerprint_secret_name"] = ""
    elif fault == "count_price":
        catalog["price_schedules"][0]["prices"][-1]["price_micro_units"] = 1
    elif fault == "disabled":
        catalog["enabled"] = False
    else:
        overrides["provider"] = "aws"
    with pytest.raises(ValueError):
        project(settings, catalog, **overrides)


@pytest.mark.parametrize(
    "material",
    [
        "-----BEGIN CERTIFICATE-----\nYWJj\n-----END CERTIFICATE-----",
        "-----BEGIN CERTIFICATE-----" + " " * 15000,
        "-----BEGIN CERTIFICATE-----\nYWJj\n-----END CERTIFICATE-----\ntrailing data",
        "-----BEGIN CERTIFICATE-----\n!invalid!\n-----END CERTIFICATE-----",
        "-----BEGIN CERTIFICATE-----\n\n-----END CERTIFICATE-----",
        "-----BEGIN OTHER-----\nYWJj\n-----END CERTIFICATE-----",
    ],
)
def test_guest_ca_rejects_malformed_or_non_x509_bundles(active_runtime, material):
    settings, catalog = active_runtime
    settings["guest_trust_ca_pem"] = material
    with pytest.raises(ValueError):
        project(settings, catalog)


def test_certificate_envelope_scan_accepts_multiple_public_blocks():
    from installation.model_broker_runtime import _validate_certificate_envelopes

    # The envelope parser checks boundaries/base64; SSL separately validates X.509.
    block = "-----BEGIN CERTIFICATE-----\nYWJj\n-----END CERTIFICATE-----"
    _validate_certificate_envelopes("\n" + block + "\n\n" + block + "\n")


def test_unsupported_deployment_provider_cannot_activate_runtime(active_runtime):
    settings, catalog = active_runtime
    with pytest.raises(ValueError, match="unsupported broker provider"):
        project(settings, catalog, provider="unknown")


@pytest.mark.parametrize("subject", [None, "", "broker", "foreign", "missing_id", "same_id", "valid"])
def test_active_gcp_projection_binds_separate_platform_provisioner(active_runtime, subject):
    from installation.gcp_model_broker import project_model_broker

    settings, catalog = active_runtime
    policy = seal_catalog(catalog)
    output = {
        "enabled": True,
        "hostname": "models.example.test",
        "vip": "10.40.0.25",
        "admitted_subnets": ["10.50.1.0/24"],
        "tls_secret_name": "broker-tls",
        "control_tls_secret_name": "control-tls",
        "trust_configmap_name": "model-ca",
        "model_projects": {"models-example": "model-invoke"},
        "region": "europe-west4",
        "gsa": "model-broker@platform-example.iam.gserviceaccount.com",
        "model_identities": {"models-example": "model-invoke@models-example.iam.gserviceaccount.com"},
    }
    if subject is not None:
        output["provisioner_subject"] = {
            "": "",
            "broker": output["gsa"],
            "foreign": "provisioner@foreign-example.iam.gserviceaccount.com",
            "valid": "provisioner@platform-example.iam.gserviceaccount.com",
            "missing_id": "provisioner@platform-example.iam.gserviceaccount.com",
            "same_id": "provisioner@platform-example.iam.gserviceaccount.com",
        }[subject]
    if subject != "missing_id":
        output["broker_subject_id"] = "123456789012345678901"
        output["provisioner_subject_id"] = (
            "123456789012345678902" if subject != "same_id" else output["broker_subject_id"]
        )
    args = {
        "catalog_json": policy.model_dump_json(),
        "model_access_env": (
            "MODEL_ACCESS_ENABLED=true\n"
            "MODEL_ACCESS_CATALOG_PATH=/etc/shifter/model-access/catalog.json\n"
            f"MODEL_ACCESS_CATALOG_DIGEST={policy.digest}\n"
        ),
        "runtime_settings": settings,
    }
    if subject == "valid":
        projected = project_model_broker(output, **args)
        assert projected["provisioner_subject"] == output["provisioner_subject"]
        assert json.loads(projected["providers_json"]) == settings["provider_inventory"]
        assert projected["enrollment_env"] == {}
    else:
        with pytest.raises(ValueError, match=r"subject|identity"):
            project_model_broker(output, **args)
