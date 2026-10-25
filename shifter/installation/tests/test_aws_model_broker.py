"""Native AWS deployment binding rejects stale policy, IAM and network readback."""

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from shared.model_access import seal_catalog

from installation.aws_model_broker import (
    AwsModelBrokerSettings,
    project_aws_model_broker,
    validate_aws_broker_intent,
)


@pytest.fixture
def deployment():
    raw = (Path(__file__).resolve().parents[3] / "docs/architecture/model-access/example-policy.v3.json").read_text()
    catalog = json.loads(raw.replace("europe-west4", "us-east-2").replace("vertex-v1", "bedrock-v1"))
    catalog.pop("digest")
    catalog["enabled"] = True
    model = "anthropic.example-model-v1:0"
    catalog["shards"][0]["provider_model"] = model
    role = "arn:aws:iam::123456789012:role/test-invoke"
    broker = {
        "enabled": True,
        "hostname": "models.example.test",
        "admitted_subnets": ["10.50.1.0/24"],
        "tls_secret_name": "broker-tls",
        "control_tls_secret_name": "control-tls",
        "trust_configmap_name": "model-ca",
        "invocation_models": {"primary": model},
    }
    runtime = {
        "provider_inventory": {
            "contract_version": "model-broker-providers/v1",
            "targets": [
                {
                    "shard_id": "vertex-primary",
                    "provider": "bedrock-v1",
                    "region": "us-east-2",
                    "model": model,
                    "principal": role,
                    "context_window_tokens": 200000,
                    "credential_reference": catalog["shards"][0]["credential_ref"]["reference"],
                }
            ],
        },
        "fingerprint_secret_name": "broker-key-v1",
        "fingerprint_key_version": "v1",
    }
    policy = seal_catalog(catalog)
    output = {
        **broker,
        "role_arn": "arn:aws:iam::123456789012:role/test-broker",
        "provisioner_subject": "arn:aws:iam::123456789012:role/test-provisioner",
        "region": "us-east-2",
        "invocation_roles": {"primary": role},
        "target_group_arn": "arn:aws:elasticloadbalancing:us-east-2:123456789012:targetgroup/models/0123456789abcdef",
        "vpc_id": "vpc-" + "1" * 17,
        "endpoint_cidrs": ["10.42.0.10/32", "10.42.0.11/32"],
        "guest_endpoint_cidrs": ["10.42.0.25/32"],
        "health_check_cidrs": ["10.42.0.0/20"],
    }
    return output, {
        "config": SimpleNamespace(
            settings={"region": "us-east-2", "model_broker": copy.deepcopy(broker), "model_broker_runtime": runtime}
        ),
        "account_id": "123456789012",
        "catalog_json": policy.model_dump_json(),
        "model_access_env": (
            "MODEL_ACCESS_ENABLED=true\n"
            "MODEL_ACCESS_CATALOG_PATH=/etc/shifter/model-access/catalog.json\n"
            f"MODEL_ACCESS_CATALOG_DIGEST={policy.digest}\n"
        ),
    }


def test_applied_native_aws_broker_binds_policy_and_separate_roles(deployment):
    output, args = deployment
    result = project_aws_model_broker(output, **args)
    assert result["role_arn"] == output["role_arn"]
    assert result["provisioner_subject"] == output["provisioner_subject"]
    assert json.loads(result["providers_json"])["targets"][0]["principal"] == output["invocation_roles"]["primary"]
    assert result["endpoint_cidrs"] == output["endpoint_cidrs"]
    assert "invocation_models" not in result
    assert "gsa" not in result


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "region",
        "account",
        "role_reuse",
        "invocation_role",
        "extra_identity",
        "target_group",
        "public_endpoint",
        "broad_endpoint",
        "no_endpoint",
        "transport",
        "extra_field",
        "runtime_role",
        "runtime_region",
    ],
)
def test_applied_drift_fails_before_helm(deployment, fault):
    output, args = deployment
    if fault == "missing":
        output = None
    elif fault == "region":
        output["region"] = "us-west-2"
    elif fault == "account":
        output["role_arn"] = output["role_arn"].replace("123456789012", "2" * 12)
    elif fault == "role_reuse":
        output["provisioner_subject"] = output["role_arn"]
    elif fault == "invocation_role":
        output["invocation_roles"]["primary"] = output["provisioner_subject"]
    elif fault == "extra_identity":
        output["invocation_roles"]["extra"] = "arn:aws:iam::123456789012:role/extra"
    elif fault == "target_group":
        output["target_group_arn"] = output["target_group_arn"].replace("us-east-2", "us-west-2")
    elif fault in {"public_endpoint", "broad_endpoint", "no_endpoint"}:
        output["endpoint_cidrs"] = {
            "public_endpoint": ["1.2.3.4/32"],
            "broad_endpoint": ["10.0.0.0/8"],
            "no_endpoint": [],
        }[fault]
    elif fault == "transport":
        output["hostname"] = "other.example.test"
    elif fault == "extra_field":
        output["provider_key"] = "forbidden"
    elif fault == "runtime_role":
        args["config"].settings["model_broker_runtime"]["provider_inventory"]["targets"][0]["principal"] = output[
            "role_arn"
        ]
    else:
        args["config"].settings["model_broker_runtime"]["provider_inventory"]["targets"][0]["region"] = "us-west-2"
    with pytest.raises(ValueError):
        project_aws_model_broker(output, **args)


@pytest.mark.parametrize("subnets", [["0.0.0.0/0"], ["10.1.0.0/16", "10.1.2.0/24"], ["10.1.0.1/24"], []])
def test_operator_transport_requires_disjoint_private_networks(deployment, subnets):
    _, args = deployment
    intent = args["config"].settings["model_broker"]
    intent["admitted_subnets"] = subnets
    with pytest.raises(ValueError):
        AwsModelBrokerSettings.model_validate(intent)


def test_disabled_projection_rejects_retained_authority():
    args = {
        "config": SimpleNamespace(settings={"region": "us-east-2"}),
        "catalog_json": "",
        "model_access_env": "",
        "account_id": "123456789012",
    }
    assert project_aws_model_broker(None, **args) == {"enabled": False}
    with pytest.raises(ValueError):
        project_aws_model_broker({"enabled": False, "role_arn": "arn:aws:iam::123456789012:role/old"}, **args)


def test_guest_listener_addresses_are_distinct_from_provider_endpoint_destinations(deployment):
    output, args = deployment
    output["guest_endpoint_cidrs"] = ["10.42.0.25/32"]
    result = project_aws_model_broker(output, **args)
    assert result["guest_endpoint_cidrs"] == ["10.42.0.25/32"]


@pytest.mark.parametrize("addresses", [[], ["0.0.0.0/0"], ["10.42.0.0/24"], ["203.0.113.7/32"]])
def test_guest_listener_readback_requires_exact_private_addresses(deployment, addresses):
    output, args = deployment
    output["guest_endpoint_cidrs"] = addresses
    with pytest.raises(ValueError):
        project_aws_model_broker(output, **args)


@pytest.mark.parametrize("fault", [None, "model", "region"])
def test_broker_intent_binds_runtime_before_cloud_mutation(deployment, fault):
    _, args = deployment
    config = args["config"]
    config.settings["model_access"] = {"enabled": True, "catalog": json.loads(args["catalog_json"])}
    if fault == "model":
        config.settings["model_broker"]["invocation_models"]["primary"] = "anthropic.other-model-v1:0"
    elif fault == "region":
        config.settings["region"] = "us-west-2"
    if fault is None:
        intent = validate_aws_broker_intent(config)
        assert intent.enabled
        assert intent.invocation_models == config.settings["model_broker"]["invocation_models"]
    else:
        with pytest.raises(ValueError, match="configured regional models"):
            validate_aws_broker_intent(config)


def test_disabled_broker_intent_and_readback_need_no_runtime():
    config = SimpleNamespace(settings={})
    assert not validate_aws_broker_intent(config).enabled
    assert project_aws_model_broker(
        {"enabled": False}, config=config, catalog_json="", model_access_env="", account_id="123456789012"
    ) == {"enabled": False}


def test_transport_can_be_prepared_before_accounting_activation(deployment):
    _, args = deployment
    config = args["config"]
    config.settings["model_access"] = {"enabled": False, "catalog": json.loads(args["catalog_json"])}
    config.settings.pop("model_broker_runtime")
    assert validate_aws_broker_intent(config).enabled


@pytest.mark.parametrize("fault", ["disabled_authority", "shared_tls"])
def test_broker_transport_rejects_retained_or_shared_authority(deployment, fault):
    _, args = deployment
    intent = args["config"].settings["model_broker"]
    if fault == "disabled_authority":
        intent["enabled"] = False
    else:
        intent["control_tls_secret_name"] = intent["tls_secret_name"]
    with pytest.raises(ValueError, match=r"disabled broker|distinct TLS"):
        AwsModelBrokerSettings.model_validate(intent)
