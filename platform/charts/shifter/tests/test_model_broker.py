"""Evaluate the rendered broker's credential and additive network boundaries."""

from __future__ import annotations

import ipaddress
import json
import subprocess
from pathlib import Path

import pytest
import yaml

CHART = Path(__file__).resolve().parents[1]


def enabled_values():
    return {
        "provider": {"name": "gcp"},
        "modelBroker": {
            "enabled": True,
            "hostname": "models.example.test",
            "vip": "10.40.0.25",
            "admitted_subnets": ["10.50.1.0/24"],
            "global_access": False,
            "tls_secret_name": "model-broker-tls-v1",
            "control_tls_secret_name": "model-control-tls-v1",
            "trust_configmap_name": "model-access-ca-v1",
            "gsa": "model-broker@platform-example.iam.gserviceaccount.com",
            "region": "us-central1",
            "catalog_json": (
                _catalog := (
                    CHART.parents[2]
                    / "docs/architecture/model-access/example-policy.v1.json"
                ).read_text()
            ),
            "identities_json": "{}",
            "catalog_digest": json.loads(_catalog)["digest"],
            "control_env": {
                "MODEL_ACCESS_ENABLED": "false",
                "MODEL_ACCESS_CATALOG_PATH": "/etc/shifter/model-access/catalog.json",
                "MODEL_ACCESS_CATALOG_DIGEST": json.loads(_catalog)["digest"],
            },
        },
        "network": {
            "providerApiCidrs": ["199.36.153.8/30"],
            "privateServiceCidrs": ["10.60.0.0/24"],
        },
        "runtimeEnv": {
            "DB_SECRET_ID": "portal-secret-sentinel",
            "DJANGO_SETTINGS_MODULE": "config.settings",
        },
    }


def render(tmp_path, values):
    path = tmp_path / "values.json"
    path.write_text(json.dumps(values))
    return subprocess.run(
        ["helm", "template", "broker-test", str(CHART), "-f", str(path)],
        text=True,
        capture_output=True,
        check=False,
    )


def aws_values():
    """Synthetic regional deployment with Terraform-owned private NLB targets."""
    values = enabled_values()
    values["provider"]["name"] = "aws"
    values["modelBroker"].update(
        {
            "gsa": "",
            "vip": "",
            "region": "us-east-2",
            "role_arn": "arn:aws:iam::123456789012:role/model-broker",
            "provisioner_subject": "arn:aws:iam::123456789012:role/provisioner",
            "target_group_arn": "arn:aws:elasticloadbalancing:us-east-2:123456789012:targetgroup/models/0123456789abcdef",
            "vpc_id": "vpc-" + "1" * 17,
            "endpoint_cidrs": ["10.42.0.10/32", "10.42.0.11/32"],
            "health_check_cidrs": ["10.42.0.0/20"],
        }
    )
    # Other applications may reach broad API destinations; broker must remain
    # isolated even when these additive policies are present.
    values["network"]["providerApiCidrs"] = ["0.0.0.0/0"]
    return values


@pytest.mark.parametrize(
    "identities", [None, ("123456789012345678901", "123456789012345678902")]
)
def test_active_control_pins_applied_immutable_google_subjects(tmp_path, identities):
    values = enabled_values()
    values["security"] = {"app": {"runAsGroup": 2000}}
    broker = values["modelBroker"]
    catalog = json.loads(
        (
            CHART.parents[2] / "docs/architecture/model-access/example-policy.v3.json"
        ).read_text()
    )
    catalog["enabled"] = True
    broker.update(
        {
            "catalog_json": json.dumps(catalog),
            "catalog_digest": catalog["digest"],
            "provisioner_subject": "provisioner@platform-example.iam.gserviceaccount.com",
            "providers_json": "{}",
            "fingerprint_secret_name": "fingerprint-v1",
            "fingerprint_key_version": "v1",
        }
    )
    broker["control_env"].update(
        MODEL_ACCESS_ENABLED="true", MODEL_ACCESS_CATALOG_DIGEST=catalog["digest"]
    )
    if identities:
        broker.update(
            broker_subject_id=identities[0], provisioner_subject_id=identities[1]
        )
    result = render(tmp_path, values)
    if identities is None:
        assert result.returncode != 0
        return
    assert result.returncode == 0, result.stderr
    broker_pod = next(
        doc["spec"]["template"]["spec"]
        for doc in yaml.safe_load_all(result.stdout)
        if doc
        and doc["kind"] == "Deployment"
        and doc["metadata"]["name"] == "model-broker"
    )
    assert broker_pod["securityContext"]["fsGroup"] == 2000
    assert broker_pod["containers"][0]["securityContext"]["runAsGroup"] == 2000
    fingerprint = next(
        volume for volume in broker_pod["volumes"] if volume["name"] == "fingerprint"
    )
    assert fingerprint["secret"]["defaultMode"] == 0o440
    control = next(
        doc
        for doc in yaml.safe_load_all(result.stdout)
        if doc
        and doc["kind"] == "Deployment"
        and doc["metadata"]["name"] == "model-access-control"
    )
    env = {
        item["name"]: item.get("value")
        for item in control["spec"]["template"]["spec"]["containers"][0]["env"]
    }
    assert env["MODEL_CONTROL_BROKER_SUBJECT_ID"] == identities[0]
    assert env["MODEL_CONTROL_PROVISIONER_SUBJECT_ID"] == identities[1]


def test_aws_broker_uses_only_private_endpoints_and_exact_irsa(tmp_path):
    result = render(tmp_path, aws_values())
    assert result.returncode == 0, result.stderr
    docs = [doc for doc in yaml.safe_load_all(result.stdout) if doc]
    by_name = {(doc["kind"], doc["metadata"]["name"]): doc for doc in docs}
    pod = by_name["Deployment", "model-broker"]["spec"]["template"]
    env = {
        item["name"]: item["value"]
        for item in pod["spec"]["containers"][0]["env"]
        if "value" in item
    }
    assert env["MODEL_BROKER_PROVIDER"] == "aws"
    assert env["AWS_EC2_METADATA_DISABLED"] == "true"
    assert env["AWS_STS_REGIONAL_ENDPOINTS"] == "regional"
    assert "envFrom" not in pod["spec"]["containers"][0]
    account = by_name["ServiceAccount", "model-broker"]
    assert account["metadata"]["annotations"] == {
        "eks.amazonaws.com/role-arn": "arn:aws:iam::123456789012:role/model-broker",
        "eks.amazonaws.com/sts-regional-endpoints": "true",
    }
    assert account["automountServiceAccountToken"] is False
    service = by_name["Service", "model-broker"]["spec"]
    assert service["type"] == "ClusterIP"
    binding = by_name["TargetGroupBinding", "model-broker"]["spec"]
    assert binding["targetType"] == "ip"
    assert binding["serviceRef"] == {"name": "model-broker", "port": 443}
    control = by_name["Deployment", "model-access-control"]["spec"]["template"]["spec"][
        "containers"
    ][0]
    control_env = {
        item["name"]: item["value"] for item in control["env"] if "value" in item
    }
    assert control_env["MODEL_CONTROL_REGION"] == "us-east-2"
    assert control_env["MODEL_CONTROL_PROVIDER"] == "aws"
    assert control_env["MODEL_CONTROL_BROKER_SUBJECT"] == env.get(
        "AWS_ROLE_ARN", account["metadata"]["annotations"]["eks.amazonaws.com/role-arn"]
    )
    policies = [
        doc["spec"]
        for doc in docs
        if doc["kind"] == "NetworkPolicy"
        and doc["metadata"]["namespace"] == "shifter-platform"
        and selected(doc["spec"]["podSelector"], pod["metadata"]["labels"])
    ]
    egress = [rule for policy in policies for rule in policy.get("egress", [])]
    assert {port["port"] for rule in egress for port in rule["ports"]} == {
        53,
        443,
        8444,
        3128,
    }
    assert {
        peer["ipBlock"]["cidr"]
        for rule in egress
        for peer in rule["to"]
        if "ipBlock" in peer
    } == {"10.42.0.10/32", "10.42.0.11/32"}
    assert "portal-secret-sentinel" not in json.dumps(pod)


@pytest.mark.parametrize(
    "fault",
    ["role_arn", "target_group_arn", "endpoint_cidrs", "health_check_cidrs", "gsa"],
)
def test_aws_broker_rejects_incomplete_or_mixed_cloud_boundary(tmp_path, fault):
    values = aws_values()
    values["modelBroker"][fault] = (
        "wrong@project-example.iam.gserviceaccount.com"
        if fault == "gsa"
        else []
        if fault.endswith("cidrs")
        else ""
    )
    assert render(tmp_path, values).returncode != 0


def selected(selector, labels):
    if any(
        labels.get(key) != value
        for key, value in selector.get("matchLabels", {}).items()
    ):
        return False
    for expression in selector.get("matchExpressions", []):
        value = labels.get(expression["key"])
        if expression["operator"] == "NotIn" and value in expression["values"]:
            return False
        if expression["operator"] == "In" and value not in expression["values"]:
            return False
    return True


def test_broker_has_isolated_process_and_effective_network_policy(tmp_path):
    result = render(tmp_path, enabled_values())
    assert result.returncode == 0, result.stderr
    docs = [doc for doc in yaml.safe_load_all(result.stdout) if doc]
    deployment = next(
        doc
        for doc in docs
        if doc["kind"] == "Deployment" and doc["metadata"]["name"] == "model-broker"
    )
    pod = deployment["spec"]["template"]
    container = pod["spec"]["containers"][0]
    assert container["command"] == ["python", "-m", "model_broker"]
    assert "envFrom" not in container
    assert all(
        "DB_" not in item["name"] and "SECRET_ID" not in item["name"]
        for item in container["env"]
    )
    assert pod["spec"]["serviceAccountName"] == "model-broker"
    assert pod["spec"]["automountServiceAccountToken"] is False
    assert "portal-secret-sentinel" not in json.dumps(deployment)
    policies = [
        doc["spec"]
        for doc in docs
        if doc["kind"] == "NetworkPolicy"
        and doc["metadata"]["namespace"] == "shifter-platform"
        and selected(doc["spec"]["podSelector"], pod["metadata"]["labels"])
    ]
    ingress = [rule for policy in policies for rule in policy.get("ingress", [])]
    assert ingress == [
        {
            "from": [{"ipBlock": {"cidr": "10.50.1.0/24"}}],
            "ports": [{"protocol": "TCP", "port": 8443}],
        }
    ]
    for source, admitted in [("10.50.1.10", True), ("10.50.2.10", False)]:
        assert (
            any(
                ipaddress.ip_address(source)
                in ipaddress.ip_network(peer["ipBlock"]["cidr"])
                for rule in ingress
                for peer in rule["from"]
            )
            is admitted
        )
    allowed_ports = {
        port["port"]
        for policy in policies
        for rule in policy.get("egress", [])
        for port in rule.get("ports", [])
    }
    assert not {5432, 6378, 6379, 8000, 6443, 6444} & allowed_ports
    assert {443, 8444, 53, 80} <= allowed_ports
    service = next(
        doc
        for doc in docs
        if doc["kind"] == "Service" and doc["metadata"]["name"] == "model-broker"
    )
    assert service["spec"]["externalTrafficPolicy"] == "Local"
    assert service["spec"]["loadBalancerIP"] == "10.40.0.25"
    assert service["spec"]["loadBalancerSourceRanges"] == ["10.50.1.0/24"]
    assert service["spec"]["ports"] == [
        {"name": "https", "port": 443, "targetPort": "https", "protocol": "TCP"}
    ]


@pytest.mark.parametrize(
    "mutation", ["provider", "network", "image", "extra_env", "missing_tls"]
)
def test_broker_render_rejects_unsafe_boundary(tmp_path, mutation):
    values = enabled_values()
    if mutation == "provider":
        values["provider"]["name"] = "aws"
    elif mutation == "network":
        values["network"]["enabled"] = False
    elif mutation == "image":
        values["images"] = {"platform": "registry.example/platform:latest"}
    elif mutation == "extra_env":
        values["modelBroker"]["env"] = {"DB_PASSWORD": "sentinel"}
    else:
        values["modelBroker"]["tls_secret_name"] = ""
    assert render(tmp_path, values).returncode != 0


def test_disabled_render_keeps_draining_broker_excluded_from_application_egress(
    tmp_path,
):
    values = enabled_values()
    values["modelBroker"] = {"enabled": False}
    result = render(tmp_path, values)
    assert result.returncode == 0, result.stderr
    policies = {
        doc["metadata"]["name"]: doc["spec"]
        for doc in yaml.safe_load_all(result.stdout)
        if doc and doc["kind"] == "NetworkPolicy"
    }
    labels = {"app.kubernetes.io/component": "model-broker"}
    for name in (
        "allow-platform-provider-apis-egress",
        "allow-platform-private-service-egress",
    ):
        assert not selected(policies[name]["podSelector"], labels)


def test_both_authorization_path_deployments_have_disruption_budgets(tmp_path):
    result = render(tmp_path, enabled_values())
    assert result.returncode == 0, result.stderr
    budgets = {
        doc["metadata"]["name"]: doc["spec"]
        for doc in yaml.safe_load_all(result.stdout)
        if doc and doc["kind"] == "PodDisruptionBudget"
    }
    for name in ("model-broker", "model-access-control"):
        assert budgets[name]["minAvailable"] == 1
        assert budgets[name]["unhealthyPodEvictionPolicy"] == "AlwaysAllow"
        assert (
            budgets[name]["selector"]["matchLabels"]["app.kubernetes.io/component"]
            == name
        )


def test_configmap_transport_rejects_oversize_identity_plus_catalog_payload(tmp_path):
    values = enabled_values()
    values["modelBroker"]["identities_json"] = json.dumps(
        {"padding": "x" * (96 * 1024)}
    )
    result = render(tmp_path, values)
    assert result.returncode != 0
    assert "ConfigMap transport" in result.stderr


@pytest.mark.parametrize(
    "field,value",
    [
        ("admitted_subnets", ["0.0.0.0/0"]),
        ("admitted_subnets", ["172.16.0.0/8"]),
        ("admitted_subnets", ["10.999.0.0/24"]),
        ("vip", "10.400.0.1"),
        ("control_tls_secret_name", "model-broker-tls-v1"),
    ],
)
def test_direct_helm_transport_rejects_invalid_network_or_shared_tls(
    tmp_path, field, value
):
    values = enabled_values()
    values["modelBroker"][field] = value
    assert render(tmp_path, values).returncode != 0


@pytest.mark.parametrize(
    "mutation,error_details",
    [
        ("missing", ("enabled model broker requires control_env",)),
        ("digest", ("model control environment must bind the mounted catalog digest",)),
        (
            "path",
            ("MODEL_ACCESS_CATALOG_PATH", "/etc/shifter/model-access/catalog.json"),
        ),
        ("unknown", ("DB_PASSWORD", "not allowed")),
        ("disabled_catalog", ("enabled model access requires an enabled catalog",)),
    ],
)
def test_control_environment_rejects_unbound_catalog(tmp_path, mutation, error_details):
    values = enabled_values()
    env = values["modelBroker"]["control_env"]
    if mutation == "missing":
        env.clear()
    elif mutation == "digest":
        env["MODEL_ACCESS_CATALOG_DIGEST"] = "sha256:" + "0" * 64
    elif mutation == "path":
        env["MODEL_ACCESS_CATALOG_PATH"] = "/tmp/unmounted.json"
    elif mutation == "unknown":
        env["DB_PASSWORD"] = "synthetic-sentinel"
    else:
        env["MODEL_ACCESS_ENABLED"] = "true"
    result = render(tmp_path, values)
    assert result.returncode != 0
    for detail in error_details:
        assert detail in result.stderr


@pytest.mark.parametrize("provider", ["gcp", "aws"])
def test_model_listeners_bind_downward_api_private_pod_address(tmp_path, provider):
    result = render(tmp_path, aws_values() if provider == "aws" else enabled_values())
    assert result.returncode == 0, result.stderr
    deployments = {
        doc["metadata"]["name"]: doc
        for doc in yaml.safe_load_all(result.stdout)
        if doc and doc["kind"] == "Deployment"
    }
    for name, variable in [
        ("model-broker", "MODEL_BROKER_BIND_ADDRESS"),
        ("model-access-control", "MODEL_CONTROL_BIND_ADDRESS"),
    ]:
        container = deployments[name]["spec"]["template"]["spec"]["containers"][0]
        binding = next(item for item in container["env"] if item["name"] == variable)
        assert binding == {
            "name": variable,
            "valueFrom": {"fieldRef": {"fieldPath": "status.podIP"}},
        }


def test_provider_egress_has_no_workload_identity_or_additive_private_access(tmp_path):
    values = enabled_values()
    values["network"]["providerApiCidrs"] = ["0.0.0.0/0"]
    result = render(tmp_path, values)
    assert result.returncode == 0, result.stderr
    docs = [doc for doc in yaml.safe_load_all(result.stdout) if doc]
    deployment = next(
        doc
        for doc in docs
        if doc["kind"] == "Deployment"
        and doc["metadata"]["name"] == "model-provider-egress"
    )
    pod = deployment["spec"]["template"]
    assert "serviceAccountName" not in pod["spec"]
    assert pod["spec"]["automountServiceAccountToken"] is False
    container = pod["spec"]["containers"][0]
    assert "envFrom" not in container
    assert container["command"] == ["python", "-m", "model_broker.egress_proxy"]
    policies = [
        doc
        for doc in docs
        if doc["kind"] == "NetworkPolicy"
        and doc["metadata"]["namespace"] == "shifter-platform"
        and selected(doc["spec"]["podSelector"], pod["metadata"]["labels"])
    ]
    assert {p["metadata"]["name"] for p in policies} == {
        "default-deny-platform",
        "allow-platform-dns-egress",
        "model-provider-egress-boundary",
    }
    boundary = next(
        p["spec"]
        for p in policies
        if p["metadata"]["name"] == "model-provider-egress-boundary"
    )
    assert boundary["ingress"] == [
        {
            "from": [
                {
                    "podSelector": {
                        "matchLabels": {"app.kubernetes.io/component": "model-broker"}
                    }
                }
            ],
            "ports": [{"protocol": "TCP", "port": 3128}],
        }
    ]
    public = next(
        peer["ipBlock"]
        for rule in boundary["egress"]
        for peer in rule["to"]
        if "ipBlock" in peer
    )
    assert {"10.0.0.0/8", "169.254.0.0/16", "127.0.0.0/8"} <= set(public["except"])
