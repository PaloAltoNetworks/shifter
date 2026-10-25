"""Behavioral tests for the explicit AWS EKS/Helm bundle lifecycle."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import aws_eks


def _config() -> SimpleNamespace:
    return SimpleNamespace(
        backend="aws",
        deployment=SimpleNamespace(name="shifter", domain="shifter.example.com", profile="dev"),
        settings={"region": "us-east-2"},
        secrets={
            "django_secret_key": "shifter/dev/app",
            "db_password": "shifter/dev/db",
        },
    )


_SECRET_ARN_PREFIX = "arn:aws:secretsmanager:us-east-2:123456789012:secret:shifter/dev/eks"


def _terraform_outputs() -> dict[str, object]:
    return {
        "cluster_name": {"value": "shifter-dev-eks"},
        "cluster_access_role_arn": {"value": "arn:aws:iam::123456789012:role/shifter-dev-eks-deployer"},
        "cluster_ca_certificate": {"value": "TFMwdExTMHRMUzFDUlVkSlRpQkRSVkpVU1VaSlEwRlVSUzB0TFMwdENn"},
        "bundle_outputs": {
            "value": {
                "vpc_id": "vpc-" + "0" * 17,
                "secret_arns": {
                    "database": f"{_SECRET_ARN_PREFIX}/database-ab",
                    "django": f"{_SECRET_ARN_PREFIX}/django-cd",
                    "redis": f"{_SECRET_ARN_PREFIX}/redis-ef",
                    "cognito": f"{_SECRET_ARN_PREFIX}/cognito-gh",
                    "guacamole-db": f"{_SECRET_ARN_PREFIX}/guacamole-db-ij",
                    "guacamole-json-auth": f"{_SECRET_ARN_PREFIX}/guacamole-json-auth-kl",
                },
                "portal_db_address": "dev-portal-db.abcdef.us-east-2.rds.amazonaws.com",
                "portal_db_port": 5432,
            }
        },
        "certificate_arn": {"value": "arn:aws:acm:us-east-2:123456789012:certificate/example"},
        "waf_acl_arn": {"value": "arn:aws:wafv2:us-east-2:123456789012:regional/webacl/example/id"},
        "workload_role_arns": {
            "value": {
                "portal": "arn:aws:iam::123456789012:role/shifter-dev-portal",
                "workers": "arn:aws:iam::123456789012:role/shifter-dev-workers",
                "ctfScheduler": "arn:aws:iam::123456789012:role/shifter-dev-ctf-scheduler",
                "migrator": "arn:aws:iam::123456789012:role/shifter-dev-migrator",
                "ingress": "arn:aws:iam::123456789012:role/shifter-dev-ingress",
                "cni": "arn:aws:iam::123456789012:role/shifter-dev-cni",
                "ebs-csi": "arn:aws:iam::123456789012:role/shifter-dev-ebs-csi",
                "efs-csi": "arn:aws:iam::123456789012:role/shifter-dev-efs-csi",
                "provisionerLauncher": "arn:aws:iam::123456789012:role/shifter-dev-provisioner-launcher",
                "provisioner": "arn:aws:iam::123456789012:role/shifter-dev-provisioner",
                "guacamoleProvisioner": "arn:aws:iam::123456789012:role/shifter-dev-guacamole-db-provisioner",
                "cluster-autoscaler": "arn:aws:iam::123456789012:role/shifter-dev-cluster-autoscaler",
            }
        },
        "runtime_env": {
            "value": {
                "AWS_REGION": "us-east-2",
                # The EKS provisioner env (range/portal coordinates) is assembled by
                # the eks-provisioner-env Terraform module and arrives merged into
                # this output; the mgmt-plane keys below are the deploy-tooling input.
                "RANGE_VPC_ID": "vpc-xxxxxxxxxxxxxxxxx",
                "RANGE_VPC_CIDR": "10.1.0.0/16",
                "OIDC_AUTH_DOMAIN": "https://shifter-dev.auth.us-east-2.amazoncognito.com",
                "OIDC_ISSUER_URL": "https://cognito-idp.us-east-2.amazonaws.com/us-east-2_example",
                "OIDC_RP_CLIENT_ID": "example-client-id",
                "OIDC_SECRET_ID": "shifter/dev/cognito",
                "QUEUE_CMS_CONSUMER_ID": "https://sqs.us-east-2.amazonaws.com/123456789012/cms",
                "QUEUE_CMS_PUBLISHER_ID": "https://sqs.us-east-2.amazonaws.com/123456789012/cms",
                "QUEUE_ENGINE_CONSUMER_ID": "https://sqs.us-east-2.amazonaws.com/123456789012/engine",
                "QUEUE_ENGINE_PUBLISHER_ID": "https://sqs.us-east-2.amazonaws.com/123456789012/engine",
                "QUEUE_MC_CONSUMER_ID": "https://sqs.us-east-2.amazonaws.com/123456789012/mc",
                "QUEUE_MC_PUBLISHER_ID": "https://sqs.us-east-2.amazonaws.com/123456789012/mc",
                "RANGE_EVENTS_TOPIC_ID": "arn:aws:sns:us-east-2:123456789012:range-events",
                "STORAGE_BUCKET_NAME": "shifter-dev-storage",
            }
        },
        "edge_client_cidrs": {"value": ["203.0.113.0/24"]},
        "ingress_source_cidrs": {"value": ["10.42.128.0/24", "10.42.129.0/24"]},
        "provider_api_cidrs": {"value": ["10.42.0.0/16"]},
        "provider_api_egress_except": {"value": ["172.20.0.0/16"]},
        "private_service_cidrs": {"value": ["10.42.0.0/16"]},
        "kubernetes_api_cidrs": {"value": ["172.20.0.0/16"]},
    }


def _images() -> dict[str, str]:
    digest = "a" * 64
    return {
        "platform": f"123456789012.dkr.ecr.us-east-2.amazonaws.com/shifter/platform@sha256:{digest}",
        "guacd": f"123456789012.dkr.ecr.us-east-2.amazonaws.com/shifter/guacd@sha256:{digest}",
        "guacamoleClient": (f"123456789012.dkr.ecr.us-east-2.amazonaws.com/shifter/guacamole-client@sha256:{digest}"),
        "provisioner": (f"123456789012.dkr.ecr.us-east-2.amazonaws.com/shifter/engine-provisioner@sha256:{digest}"),
    }


def _terraform_inputs() -> dict[str, object]:
    return {
        "aws_region": "us-east-2",
        "deployment_role_arn": "arn:aws:iam::123456789012:role/shifter-dev-deployer",
        "domain_name": "shifter.example.com",
        "edge_client_cidrs": ["203.0.113.0/24"],
        "addon_versions": {
            "vpc_cni": "v1.22.4-eksbuild.3",
            "ebs_csi": "v1.63.1-eksbuild.1",
            "efs_csi": "v3.4.1-eksbuild.1",
            "coredns": "v1.11.4-eksbuild.40",
            "kube_proxy": "v1.31.14-eksbuild.25",
            "secrets_store_csi": "v3.1.2-eksbuild.1",
        },
        "provider_api_cidrs": ["10.42.0.0/16"],
        "runtime_env": _terraform_outputs()["runtime_env"]["value"],
    }


def test_acquisition_egress_keeps_the_provider_api_posture():
    """The acquisition Job gets the provider-API HTTPS egress with the service CIDR carved out."""
    outputs = _terraform_outputs()
    values = aws_eks.render_aws_values(_config(), outputs, _images())

    assert values["featureArtifactAcquisition"] == {
        "serviceAccountAnnotations": {},
        "egressCidrs": outputs["provider_api_cidrs"]["value"],
        "egressExcept": outputs["provider_api_egress_except"]["value"],
    }


def test_alb_health_checks_use_each_services_readiness_probe_path():
    """ALB target health must probe the same endpoint Kubernetes readiness does."""
    import yaml

    values = aws_eks.render_aws_values(_config(), _terraform_outputs(), _images())
    templates = Path(__file__).resolve().parents[3] / "platform/charts/shifter/templates"

    def readiness_path(template: str) -> str:
        text = (templates / template).read_text(encoding="utf-8")
        body = "\n".join(line for line in text.splitlines() if "{{" not in line and "}}" not in line)
        deployment = next(doc for doc in yaml.safe_load_all(body) if isinstance(doc, dict))
        return deployment["spec"]["template"]["spec"]["containers"][0]["readinessProbe"]["httpGet"]["path"]

    annotations = {name: service["annotations"] for name, service in values["services"].items()}
    assert annotations == {
        "portal": {"alb.ingress.kubernetes.io/healthcheck-path": readiness_path("web-deployment.yaml")},
        "guacamoleClient": {
            "alb.ingress.kubernetes.io/healthcheck-path": readiness_path("guacamole-client-deployment.yaml")
        },
    }


def test_render_values_is_non_secret_backend_neutral_and_digest_pinned():
    values = aws_eks.render_aws_values(_config(), _terraform_outputs(), _images())

    assert values["provider"]["name"] == "aws"
    assert values["capabilities"]["kubernetesJobLauncher"] is True
    assert values["provisioner"]["taskRunner"] == "aws"
    sa_roles = values["identity"]["serviceAccountRoleArns"]
    assert sa_roles["provisionerLauncher"].endswith("shifter-dev-provisioner-launcher")
    assert sa_roles["provisioner"].endswith("shifter-dev-provisioner")
    assert values["edge"]["hostname"] == "shifter.example.com"
    assert values["edge"]["ingress"]["className"] == "alb"
    assert values["edge"]["ingress"]["annotations"]["alb.ingress.kubernetes.io/certificate-arn"].endswith(
        "certificate/example"
    )
    assert (
        values["edge"]["ingress"]["annotations"]["alb.ingress.kubernetes.io/load-balancer-name"]
        == "shifter-dev-eks-platform"
    )
    assert values["network"]["ingressSourceCidrs"] == ["10.42.128.0/24", "10.42.129.0/24"]
    assert values["edge"]["ingress"]["annotations"]["alb.ingress.kubernetes.io/inbound-cidrs"] == "203.0.113.0/24"
    assert values["network"]["kubernetesApiCidrs"] == ["172.20.0.0/16"]
    # The service CIDR is carved out of the wildcard provider-API egress so the
    # broad 443 allow cannot reach the in-cluster Kubernetes API (#1826).
    assert values["network"]["providerApiEgressExcept"] == ["172.20.0.0/16"]
    # The provisioner Job must reach range guests over SSH to bootstrap them; the
    # range-access egress policy renders only when the range CIDR is populated,
    # sourced from the same RANGE_VPC_CIDR the provisioner targets (#1826).
    assert values["network"]["rangeAccessCidrs"] == ["10.1.0.0/16"]
    assert values["network"]["rangeAccessPorts"] == [22, 3389]
    assert values["identity"]["serviceAccountRoleArns"]["portal"].endswith("shifter-dev-portal")
    assert values["identity"]["serviceAccountRoleArns"]["workers"].endswith("shifter-dev-workers")
    assert values["identity"]["serviceAccountRoleArns"]["ctfScheduler"].endswith("shifter-dev-ctf-scheduler")
    assert values["runtimeEnv"]["CLOUD_PROVIDER"] == "aws"
    assert values["runtimeEnv"]["AUDIT_DEPLOYMENT_SCOPE"] == "aws:123456789012:us-east-2:dev"
    assert values["runtimeEnv"]["ENVIRONMENT"] == "development"
    assert values["runtimeEnv"]["AUTH_PROVIDER"] == "oidc"
    # ENGINE_TASK_IMAGE is renderer-generated from the attested provisioner digest.
    assert values["runtimeEnv"]["ENGINE_TASK_IMAGE"].endswith("engine-provisioner@sha256:" + ("a" * 64))
    # Provisioner env assembled by Terraform flows through the merged output.
    assert values["runtimeEnv"]["RANGE_VPC_ID"] == "vpc-xxxxxxxxxxxxxxxxx"
    assert values["runtimeEnv"]["QUEUE_ENGINE_CONSUMER_ID"].endswith("/engine")
    # OIDC_SECRET_ID is repointed from the portal-owned cognito secret to the
    # eks-owned copy the portal role can read (populated before Helm).
    assert (
        values["runtimeEnv"]["OIDC_SECRET_ID"]
        == "arn:aws:secretsmanager:us-east-2:123456789012:secret:shifter/dev/eks/cognito-gh"
    )
    # secretReferences come from the eks module's secret_arns (which the portal
    # IRSA role can read), not the deploy config, so the empty eks-owned secrets
    # are what the portal hydrates once _populate_eks_workload_secrets fills them.
    assert values["runtime"]["secretReferences"] == {
        "app": "arn:aws:secretsmanager:us-east-2:123456789012:secret:shifter/dev/eks/django-cd",
        "database": "arn:aws:secretsmanager:us-east-2:123456789012:secret:shifter/dev/eks/database-ab",
    }
    rendered = json.dumps(values)
    assert "@sha256:" in rendered
    assert "SECRET_KEY=" not in rendered
    assert "PASSWORD=" not in rendered


def _broker_intent():
    return {
        "enabled": True,
        "hostname": "models.example.test",
        "admitted_subnets": ["10.50.1.0/24"],
        "tls_secret_name": "broker-tls",
        "control_tls_secret_name": "control-tls",
        "trust_configmap_name": "model-ca",
        "invocation_models": {"primary": "anthropic.example-model-v1:0"},
    }


def _standby_broker_config():
    config = _config()
    config.settings["model_broker"] = _broker_intent()
    catalog_path = Path(__file__).resolve().parents[3] / "docs/architecture/model-access/example-policy.v3.json"
    config.settings["model_access"] = {"enabled": False, "catalog": json.loads(catalog_path.read_text())}
    return config


def test_renderer_binds_applied_broker_to_platform_roles_and_endpoints():
    config = _standby_broker_config()
    outputs = _terraform_outputs()
    outputs["model_broker"] = {
        "value": {
            **_broker_intent(),
            "role_arn": "arn:aws:iam::123456789012:role/model-broker",
            "provisioner_subject": outputs["workload_role_arns"]["value"]["provisioner"],
            "region": "us-east-2",
            "invocation_roles": {"primary": "arn:aws:iam::123456789012:role/model-invoke"},
            "target_group_arn": (
                "arn:aws:elasticloadbalancing:us-east-2:123456789012:targetgroup/models/0123456789abcdef"
            ),
            "vpc_id": "vpc-" + "1" * 17,
            "endpoint_cidrs": ["10.42.0.10/32"],
            "guest_endpoint_cidrs": ["10.42.0.25/32"],
            "health_check_cidrs": ["10.42.0.0/20"],
        }
    }
    values = aws_eks.render_aws_values(config, outputs, _images())
    assert values["modelBroker"]["enabled"] is True
    assert values["modelBroker"]["control_env"]["MODEL_ACCESS_ENABLED"] == "false"
    assert "10.42.0.10/32" in values["network"]["providerApiCidrs"]
    assert values["runtimeEnv"]["MODEL_BROKER_GUEST_URL"] == ""
    outputs["model_broker"]["value"]["provisioner_subject"] = "arn:aws:iam::123456789012:role/unrelated"
    with pytest.raises(ValueError, match="enrollment identity differs"):
        aws_eks.render_aws_values(config, outputs, _images())


def test_protected_input_cannot_silently_disable_requested_broker(tmp_path):
    path = tmp_path / "eks.tfvars.json"
    payload = _terraform_inputs()
    path.write_text(json.dumps(payload))
    config = _standby_broker_config()
    with pytest.raises(ValueError, match="broker input differs"):
        aws_eks._validate_terraform_inputs(path, config, allowed_roots=(tmp_path,))
    payload["model_broker"] = _broker_intent()
    path.write_text(json.dumps(payload))
    assert aws_eks._validate_terraform_inputs(path, config, allowed_roots=(tmp_path,)) == path


def test_render_values_rejects_incomplete_runtime_contract():
    outputs = _terraform_outputs()
    outputs["runtime_env"]["value"].pop("OIDC_ISSUER_URL")
    config = _config()
    images = _images()

    with pytest.raises(ValueError, match="OIDC_ISSUER_URL"):
        aws_eks.render_aws_values(config, outputs, images)


def test_render_values_requires_provisioner_image_for_job_launcher():
    outputs = _terraform_outputs()
    config = _config()
    images = _images()
    images.pop("provisioner")

    with pytest.raises(ValueError, match="provisioner"):
        aws_eks.render_aws_values(config, outputs, images)


def test_effective_irsa_probe_uses_exact_service_accounts_and_cleans_up(monkeypatch):
    roles = _terraform_outputs()["workload_role_arns"]["value"]
    manifests: list[dict[str, object]] = []
    calls: list[list[str]] = []
    pod_identities: dict[str, str] = {}

    def runner(cmd, **_kwargs):
        calls.append(cmd)
        if cmd[:3] == ["kubectl", "apply", "-f"]:
            manifest = json.loads(Path(cmd[3]).read_text())
            manifests.append(manifest)
            pod_identities[manifest["metadata"]["name"]] = manifest["metadata"]["labels"]["shifter.dev/irsa-check"]
        if cmd[:2] == ["kubectl", "logs"]:
            identity = pod_identities[cmd[2]]
            return SimpleNamespace(stdout=f"IRSA_OK:{identity}\n")
        return SimpleNamespace(stdout="")

    monkeypatch.setattr(aws_eks, "run_cmd", runner)
    aws_eks._verify_effective_irsa(roles, _images()["platform"])

    assert len(manifests) == len(aws_eks._IRSA_PROBE_IDENTITIES)
    for manifest in manifests:
        spec = manifest["spec"]
        identity = manifest["metadata"]["labels"]["shifter.dev/irsa-check"]
        namespace, service_account = aws_eks._IRSA_PROBE_IDENTITIES[identity]
        assert manifest["metadata"]["namespace"] == namespace
        assert spec["serviceAccountName"] == service_account
        environment = {entry["name"]: entry["value"] for entry in spec["containers"][0]["env"]}
        assert environment["SHIFTER_EXPECTED_ROLE_ARN"] == roles[identity]
        assert json.loads(environment["SHIFTER_SIBLING_ROLE_ARNS"]) == [
            roles[name] for name in sorted(aws_eks._IRSA_PROBE_IDENTITIES) if name != identity
        ]
        rendered = json.dumps(manifest)
        assert "with open(token_path" in rendered
        assert "WebIdentityToken=token" in rendered
        assert "AWS_WEB_IDENTITY_TOKEN_FILE" in rendered
        assert "secretAccessKey" not in rendered
    assert sum(cmd[:3] == ["kubectl", "delete", "pod"] for cmd in calls) == len(manifests)


def test_effective_irsa_probe_fails_closed_on_missing_success_evidence(monkeypatch):
    calls: list[list[str]] = []

    def runner(cmd, **_kwargs):
        calls.append(cmd)
        if cmd[:2] == ["kubectl", "logs"]:
            return SimpleNamespace(stdout="")
        return SimpleNamespace(stdout="")

    monkeypatch.setattr(aws_eks, "run_cmd", runner)
    roles = _terraform_outputs()["workload_role_arns"]["value"]
    platform_image = _images()["platform"]

    with pytest.raises(RuntimeError, match="effective IRSA readiness failed"):
        aws_eks._verify_effective_irsa(roles, platform_image)

    assert any(cmd[:3] == ["kubectl", "delete", "pod"] for cmd in calls)


def test_kubernetes_security_probe_requires_admission_denial_and_live_networkpolicy(monkeypatch):
    manifests: list[dict[str, object]] = []
    calls: list[list[str]] = []
    rejected_manifests: list[dict[str, object]] = []

    def runner(cmd, **kwargs):
        calls.append(cmd)
        if "-f" in cmd:
            manifests.append(json.loads(Path(cmd[cmd.index("-f") + 1]).read_text()))
        if cmd[:3] == ["kubectl", "get", "validatingadmissionpolicy"]:
            return SimpleNamespace(stdout="Fail")
        if cmd[:3] == ["kubectl", "get", "validatingadmissionpolicybinding"]:
            return SimpleNamespace(stdout="Deny")
        if cmd[:2] == ["kubectl", "logs"]:
            workload = "deployment" if "deployment/" in cmd[2] else "job"
            return SimpleNamespace(stdout=f"NETWORK_POLICY_OK:{workload}\n")
        return SimpleNamespace(stdout="")

    monkeypatch.setattr(aws_eks, "run_cmd", runner)
    monkeypatch.setattr(
        aws_eks,
        "run_cmd_secret_stdin",
        lambda cmd, *, secret_stdin: calls.append(cmd) or rejected_manifests.append(json.loads(secret_stdin)) or 1,
    )
    aws_eks._verify_kubernetes_security_enforcement(_images()["platform"])

    assert {manifest["kind"] for manifest in manifests} == {"Deployment", "Job"}
    assert rejected_manifests[0]["spec"]["template"]["spec"]["serviceAccountName"] == "provisioner"
    assert any(cmd[:2] == ["kubectl", "create"] and "--dry-run=server" in cmd for cmd in calls)
    assert any(cmd[:3] == ["kubectl", "delete", "deployment"] for cmd in calls)
    assert any(cmd[:3] == ["kubectl", "delete", "job"] for cmd in calls)
    rendered = json.dumps(manifests)
    assert "kubernetes.default.svc" in rendered
    assert "secret" not in rendered.lower()
    deployment = next(manifest for manifest in manifests if manifest["kind"] == "Deployment")
    pod_spec = deployment["spec"]["template"]["spec"]
    container = pod_spec["containers"][0]
    assert container["readinessProbe"]["exec"]["command"] == [
        "test",
        "-f",
        "/var/run/shifter-readiness/networkpolicy-ok",
    ]
    assert container["volumeMounts"] == [{"name": "readiness", "mountPath": "/var/run/shifter-readiness"}]
    assert pod_spec["volumes"] == [{"name": "readiness", "emptyDir": {}}]
    assert "/var/run/shifter-readiness/networkpolicy-ok" in container["command"][2]


@pytest.mark.parametrize(
    ("policy_mode", "dry_run_code", "bad_log", "error"),
    [
        ("Ignore", 1, None, "not active in fail-closed deny mode"),
        ("Fail", 0, None, "admitted a non-launcher Job"),
        ("Fail", 1, "deployment", "NetworkPolicy readiness failed for deployment"),
        ("Fail", 1, "job", "NetworkPolicy readiness failed for job"),
    ],
)
def test_kubernetes_security_probe_fails_closed_on_missing_enforcement_evidence(
    monkeypatch, policy_mode, dry_run_code, bad_log, error
):
    calls: list[list[str]] = []

    def runner(cmd, **_kwargs):
        calls.append(cmd)
        if cmd[:3] == ["kubectl", "get", "validatingadmissionpolicy"]:
            return SimpleNamespace(stdout=policy_mode)
        if cmd[:3] == ["kubectl", "get", "validatingadmissionpolicybinding"]:
            return SimpleNamespace(stdout="Deny")
        if cmd[:2] == ["kubectl", "logs"]:
            workload = "deployment" if "deployment/" in cmd[2] else "job"
            evidence = "" if workload == bad_log else f"NETWORK_POLICY_OK:{workload}\n"
            return SimpleNamespace(stdout=evidence)
        return SimpleNamespace(stdout="")

    monkeypatch.setattr(aws_eks, "run_cmd", runner)
    monkeypatch.setattr(
        aws_eks,
        "run_cmd_secret_stdin",
        lambda _cmd, *, secret_stdin: dry_run_code,
    )
    platform_image = _images()["platform"]

    with pytest.raises(RuntimeError, match=error):
        aws_eks._verify_kubernetes_security_enforcement(platform_image)

    applied = [cmd for cmd in calls if cmd[:3] == ["kubectl", "apply", "-f"]]
    if policy_mode != "Fail" or dry_run_code == 0:
        assert applied == []
    else:
        assert len(applied) == 2
        assert any(cmd[:3] == ["kubectl", "delete", "deployment"] for cmd in calls)
        assert any(cmd[:3] == ["kubectl", "delete", "job"] for cmd in calls)


@pytest.mark.parametrize(
    "image",
    [
        "repo/platform:latest",
        "repo/platform@sha256:short",
        "repo/platform@sha256:" + ("g" * 64),
        "repo/platform@sha256:" + ("a" * 64) + ":tag",
    ],
)
def test_render_values_rejects_non_attested_image_identities(image):
    images = _images()
    images["platform"] = image
    config = _config()
    outputs = _terraform_outputs()

    with pytest.raises(ValueError, match="repository@sha256"):
        aws_eks.render_aws_values(config, outputs, images)


def test_generated_outputs_cover_the_terraform_provisioner_env():
    # Independent Terraform-derived oracle (#1828 codex cycle 2): parse the range/portal
    # topology keys the eks-provisioner-env module actually re-supplies into the merged
    # runtime env, and assert every one is classified in the generated-output inventory. This
    # reads the real Terraform, so a new provisioner_env key that the Python inventory forgot
    # to classify fails here even though a fixture-derived oracle would stay green.
    import re

    from installation import runtime_inventory_aws as inv

    tf_path = Path(__file__).resolve().parents[3] / "platform/terraform/modules/portal/eks-provisioner-env/main.tf"
    block = re.search(r"provisioner_env\s*=\s*\{(.*?)\n\s*\}", tf_path.read_text(encoding="utf-8"), re.DOTALL)
    assert block is not None, "could not locate the provisioner_env block in the eks-provisioner-env module"
    terraform_keys = set(re.findall(r"^\s*([A-Z][A-Z0-9_]*)\s*=", block.group(1), re.MULTILINE))
    assert terraform_keys, "parsed no keys from the Terraform provisioner_env block"

    missing = terraform_keys - set(inv.AWS_GENERATED_RUNTIME_ENV_KEYS)
    assert not missing, f"Terraform provisioner_env keys missing from AWS_GENERATED_RUNTIME_ENV_KEYS: {sorted(missing)}"
    # The hydrated-secret key is excluded from the Terraform ConfigMap surface by design.
    assert "DC_DOMAIN_PASSWORD" not in terraform_keys


def test_generated_outputs_match_a_representative_render():
    # Renderer-transformation oracle (#1828): assert render_aws_values emits into the
    # ConfigMap-bound runtimeEnv exactly the classified bundle projection, and that the keys
    # it adds on top of its Terraform input are exactly the declared renderer-owned set. The
    # complementary Terraform-derived coverage (a new pass-through key) is asserted by
    # test_generated_outputs_cover_the_terraform_provisioner_env above.
    from installation import runtime_inventory_aws as inv
    from installation.contract import OutputKind
    from installation.registry import get_backend_bundle

    # What Terraform supplies into runtime_env: the complete emitted set minus the
    # renderer-owned keys (render_aws_values adds those itself and rejects them as input).
    terraform_supplied = sorted(inv.AWS_GENERATED_RUNTIME_ENV_KEYS - inv.AWS_RENDERER_OWNED_RUNTIME_ENV_KEYS)
    outputs = _terraform_outputs()
    outputs["runtime_env"] = {"value": {key: f"value-for-{key}" for key in terraform_supplied}}

    values = aws_eks.render_aws_values(_config(), outputs, _images())
    emitted = set(values["runtimeEnv"])

    bundle = get_backend_bundle("aws")
    projected = {o.name for o in bundle.generated_outputs if o.kind is OutputKind.RUNTIME_ENV}
    assert emitted == projected, f"bundle projection drifted from renderer output: {emitted ^ projected}"

    # The keys render_aws_values adds on top of the Terraform input must be exactly the
    # declared renderer-owned set — a new renderer-owned key that is not inventoried would
    # otherwise land in the ConfigMap unclassified.
    added_by_renderer = emitted - set(outputs["runtime_env"]["value"])
    assert added_by_renderer == set(inv.AWS_RENDERER_OWNED_RUNTIME_ENV_KEYS)

    # The hydrated-secret key never enters the ConfigMap-bound runtimeEnv.
    assert "DC_DOMAIN_PASSWORD" not in emitted


def test_deploy_sequence_uses_saved_plan_bounded_access_and_atomic_helm(tmp_path, monkeypatch):
    config_path = tmp_path / "shifter.yaml"
    config_path.write_text("placeholder")
    image_path = tmp_path / "images.json"
    image_path.write_text(json.dumps(_images()))
    backend_config_path = tmp_path / "dev.s3.tfbackend"
    backend_config_path.write_text('bucket = "state"\n')
    terraform_inputs_path = tmp_path / "eks.tfvars.json"
    terraform_inputs_path.write_text(json.dumps(_terraform_inputs()))
    calls: list[list[str]] = []
    manifests: list[dict[str, object]] = []
    secret_stdin_calls: list[tuple[list[str], str]] = []
    outputs_json = json.dumps(_terraform_outputs())

    def _runner(cmd, **kwargs):
        calls.append(cmd)
        if cmd[:3] == ["kubectl", "apply", "-f"]:
            manifests.append(json.loads(Path(cmd[cmd.index("-f") + 1]).read_text()))
        if cmd[:3] == ["aws", "secretsmanager", "get-secret-value"]:
            secret_id = cmd[cmd.index("--secret-id") + 1]
            if "guacamole-json-auth" in secret_id:
                return SimpleNamespace(stdout="deadbeef" * 8 + "\n", returncode=0)
            if "guacamole-db" in secret_id:
                payload = {"username": "guacamole_admin", "password": "guac-pw", "dbname": "guacamole"}
                return SimpleNamespace(stdout=json.dumps(payload) + "\n", returncode=0)
            return SimpleNamespace(stdout="{}\n", returncode=0)
        return SimpleNamespace(stdout=outputs_json, returncode=0)

    runner = Mock(side_effect=_runner)
    monkeypatch.setattr(aws_eks, "load_root_config", lambda _path: _config())
    monkeypatch.setattr(aws_eks, "run_cmd", runner)
    monkeypatch.setattr(
        aws_eks,
        "run_cmd_secret_stdin",
        lambda cmd, *, secret_stdin: secret_stdin_calls.append((cmd, secret_stdin)) or 0,
    )
    preflight = Mock()
    monkeypatch.setattr(aws_eks, "preflight_gate", preflight)
    irsa_verify = Mock()
    monkeypatch.setattr(aws_eks, "_verify_effective_irsa", irsa_verify)
    security_verify = Mock()
    monkeypatch.setattr(aws_eks, "_verify_kubernetes_security_enforcement", security_verify)

    evidence = aws_eks.deploy_eks(
        config_path,
        image_path,
        backend_config_path=backend_config_path,
        terraform_inputs_path=terraform_inputs_path,
        aws_profile="operator",
        dry_run=False,
    )

    # The EKS deploy lifecycle must preflight the EKS component, not the legacy
    # core/range/portal defaults (#1828).
    assert preflight.call_args is not None
    assert preflight.call_args.kwargs.get("component") == "eks"

    terraform_root = str(aws_eks.eks_root("dev"))
    assert [
        "terraform",
        f"-chdir={terraform_root}",
        "init",
        "-input=false",
        "-reconfigure",
        f"-backend-config={backend_config_path}",
    ] in calls
    assert [
        "terraform",
        f"-chdir={terraform_root}",
        "plan",
        "-input=false",
        f"-var-file={terraform_inputs_path}",
        "-out=shifter-eks.tfplan",
    ] in calls
    assert ["terraform", f"-chdir={terraform_root}", "apply", "shifter-eks.tfplan"] in calls
    # The private API endpoint is unresolvable from the runner VPC (service-owned
    # hosted zone), so the deploy reaches it by control-plane ENI IP over the
    # runner<->EKS peering, with tls-server-name preserving cert validation and the
    # bounded cluster-access role for auth (no public ingress).
    assert any(cmd[:3] == ["aws", "ec2", "describe-network-interfaces"] for cmd in calls)
    kubeconfig_path = os.environ.get("KUBECONFIG")
    assert kubeconfig_path is not None
    built = json.loads(Path(kubeconfig_path).read_text())
    built_cluster = built["clusters"][0]["cluster"]
    assert built_cluster["server"].startswith("https://") and built_cluster["server"].endswith(":443")
    assert built_cluster["tls-server-name"]
    assert built_cluster["certificate-authority-data"]
    # Auth is the deploy role directly (it holds the cluster's ClusterAdmin access
    # entry). No --role-arn: passing the deploy role there self-assumes and fails
    # with AssumeRole AccessDenied.
    exec_args = built["users"][0]["user"]["exec"]["args"]
    assert "get-token" in exec_args and "--cluster-name" in exec_args
    assert "--role-arn" not in exec_args
    expected_addons = {
        "vpc-cni",
        "aws-ebs-csi-driver",
        "aws-efs-csi-driver",
        "coredns",
        "kube-proxy",
        "aws-secrets-store-csi-driver-provider",
    }
    waited_addons = {
        cmd[cmd.index("--addon-name") + 1]
        for cmd in calls
        if cmd[:3] == ["aws", "eks", "wait"] and "--addon-name" in cmd
    }
    assert waited_addons == expected_addons
    # On-disk `kubectl apply -f <file>` carries only non-secret manifests (two
    # platform-namespace manifests + the guacamole provisioner ServiceAccount and Job).
    assert sum(cmd[:3] == ["kubectl", "apply", "-f"] for cmd in calls) == 4
    # Secret- and reference-bearing manifests are streamed to kubectl over stdin, never
    # written to disk (#1826 CodeQL clear-text-storage fix): the guacamole-runtime Secret
    # and the migration prerequisites + Job all go through `kubectl apply -f -`.
    stdin_applied = [
        json.loads(secret_stdin)
        for cmd, secret_stdin in secret_stdin_calls
        if cmd[:4] == ["kubectl", "apply", "-f", "-"]
    ]
    assert any(m.get("kind") == "Secret" for m in stdin_applied)  # guacamole-runtime Secret, via stdin
    assert not any(m.get("kind") == "Secret" for m in manifests)  # never written to a temp file
    # The dedicated pre-helm migration Job (#1826) runs the single schema migration +
    # content bootstrap, is awaited to completion, and is deleted afterward.
    assert any(cmd[:2] == ["kubectl", "wait"] and f"job/{aws_eks._MIGRATION_JOB}" in cmd for cmd in calls)
    assert any(cmd[:4] == ["kubectl", "delete", "job", aws_eks._MIGRATION_JOB] for cmd in calls)
    migration_manifests = [
        m
        for m in stdin_applied
        if m.get("kind") == "List"
        and any(item.get("metadata", {}).get("name") == "platform-runtime" for item in m.get("items", []))
    ]
    assert len(migration_manifests) == 1
    migration_items = {item["kind"]: item for item in migration_manifests[0]["items"]}
    # The SA + ConfigMap carry Helm-ownership metadata so the chart adopts them.
    for item in migration_items.values():
        assert item["metadata"]["annotations"]["meta.helm.sh/release-name"] == "shifter"
        assert item["metadata"]["labels"]["app.kubernetes.io/managed-by"] == "Helm"
    assert migration_items["ServiceAccount"]["metadata"]["annotations"]["eks.amazonaws.com/role-arn"].endswith(
        "shifter-dev-migrator"
    )
    # The ConfigMap replicates the runtime env plus the two secret references.
    migration_cfg = migration_items["ConfigMap"]["data"]
    assert migration_cfg["SKIP_MIGRATIONS"] == "1"
    assert migration_cfg["APP_SECRET_ID"] and migration_cfg["DB_SECRET_ID"]
    # The Job overrides SKIP_MIGRATIONS to "" so the entrypoint migrates once.
    migrate_job = next(
        m for m in stdin_applied if m.get("kind") == "Job" and m["metadata"]["name"] == aws_eks._MIGRATION_JOB
    )
    job_env = {e["name"]: e.get("value") for e in migrate_job["spec"]["template"]["spec"]["containers"][0]["env"]}
    assert job_env["SKIP_MIGRATIONS"] == ""
    assert migrate_job["spec"]["template"]["spec"]["containers"][0]["args"][-1] == (
        "python manage.py bootstrap_inbox_catalog && python manage.py seed_raes_image_registry"
        " && python manage.py acquire_feature_artifacts"
    )
    # Guacamole provisioning: the guacamole-db + json-auth secrets are read, and the
    # provisioner Job is awaited to completion before Helm runs.
    read_secret_ids = [
        cmd[cmd.index("--secret-id") + 1]
        for cmd in calls
        if cmd[:3] == ["aws", "secretsmanager", "get-secret-value"] and "--secret-id" in cmd
    ]
    assert any("guacamole-db" in sid for sid in read_secret_ids)
    assert any("guacamole-json-auth" in sid for sid in read_secret_ids)
    assert any(cmd[:2] == ["kubectl", "wait"] and "job/guacamole-db-provision" in cmd for cmd in calls)
    assert any(
        cmd[:4] == ["helm", "upgrade", "--install", "aws-load-balancer-controller"]
        and "--version" in cmd
        and "3.2.2" in cmd
        for cmd in calls
    )
    assert [
        "kubectl",
        "rollout",
        "status",
        "deployment/aws-load-balancer-controller",
        "--namespace",
        "kube-system",
        "--timeout=5m",
    ] in calls
    assert any(
        cmd[:4] == ["helm", "upgrade", "--install", "cluster-autoscaler"]
        and "autoscaler/cluster-autoscaler" in cmd
        and "--version" in cmd
        and "autoDiscovery.clusterName=shifter-dev-eks" in cmd
        and "awsRegion=us-east-2" in cmd
        for cmd in calls
    )
    assert [
        "kubectl",
        "rollout",
        "status",
        "deployment/cluster-autoscaler-aws-cluster-autoscaler",
        "--namespace",
        "kube-system",
        "--timeout=5m",
    ] in calls
    assert any(
        cmd[:4] == ["helm", "upgrade", "--install", "shifter"] and {"--atomic", "--wait", "--values", "-"} <= set(cmd)
        for cmd, _values in secret_stdin_calls
    )
    helm_values_calls = [values for cmd, values in secret_stdin_calls if "--values" in cmd]
    apply_stdin_calls = [values for cmd, values in secret_stdin_calls if cmd[:4] == ["kubectl", "apply", "-f", "-"]]
    assert len(helm_values_calls) == 3  # helm lint + template + upgrade --install, values over stdin
    assert len(apply_stdin_calls) == 3  # guacamole-runtime Secret + migration prerequisites + Job, over stdin
    # Helm values stream the secret references over stdin, never argv or disk.
    assert all('"secretReferences"' in values for values in helm_values_calls)
    # Secret references never reach run_cmd argv (they flow only through the stdin path).
    assert not any("shifter/dev/app" in token for call in calls for token in call)
    assert not any("destroy" in cmd for cmd in calls)
    irsa_verify.assert_called_once()
    security_verify.assert_called_once()
    assert evidence["backend"] == "aws"
    assert evidence["profile"] == "dev"
    assert evidence["health_url"] == "https://shifter.example.com/health/"


def test_teardown_is_scoped_to_the_eks_root_and_fails_without_valid_aws_config(tmp_path, monkeypatch):
    config_path = tmp_path / "shifter.yaml"
    config_path.write_text("placeholder")
    calls: list[list[str]] = []
    monkeypatch.setattr(aws_eks, "load_root_config", lambda _path: _config())
    monkeypatch.setattr(aws_eks, "run_cmd", lambda cmd, **kwargs: calls.append(cmd))

    backend_config_path = tmp_path / "dev.s3.tfbackend"
    backend_config_path.write_text('bucket = "state"\n')
    terraform_inputs_path = tmp_path / "eks.tfvars.json"
    terraform_inputs_path.write_text(json.dumps(_terraform_inputs()))

    aws_eks.teardown_eks(
        config_path,
        backend_config_path=backend_config_path,
        terraform_inputs_path=terraform_inputs_path,
        aws_profile="operator",
        dry_run=False,
    )

    root = str(aws_eks.eks_root("dev"))
    assert calls[0][:4] == ["helm", "uninstall", "shifter", "--namespace"]
    assert [
        "terraform",
        f"-chdir={root}",
        "init",
        "-input=false",
        "-reconfigure",
        f"-backend-config={backend_config_path}",
    ] in calls
    assert [
        "terraform",
        f"-chdir={root}",
        "destroy",
        "-auto-approve",
        f"-var-file={terraform_inputs_path}",
    ] in calls
    assert not any("/portal" in token or "/range" in token for call in calls for token in call)


def test_protected_input_reader_rejects_paths_outside_approved_roots(tmp_path):
    approved_root = tmp_path / "approved"
    approved_root.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text("{}")

    with pytest.raises(ValueError, match="approved protected-input root"):
        aws_eks._read_json_mapping(
            outside,
            label="test input",
            allowed_roots=(approved_root,),
        )


def test_protected_input_reader_rejects_symbolic_links(tmp_path):
    target = tmp_path / "target.json"
    target.write_text("{}")
    link = tmp_path / "link.json"
    link.symlink_to(target)

    with pytest.raises(ValueError, match="symbolic link"):
        aws_eks._read_json_mapping(
            link,
            label="test input",
            allowed_roots=(tmp_path,),
        )


# --- Negative-path coverage for the deploy-safety guards (#1828 test-quality cycle 1) ------
# These lock the failure branches of the aws_eks validation guards: replacing any raise below
# with a no-op must fail a test. Without them a refactor could silently drop the region/domain
# cross-check that stops a mismatched Terraform var-file from applying against the wrong
# shifter.yaml, the protected-input JSON hardening, or the IRSA precondition checks.


def test_validate_config_rejects_non_aws_backend():
    config = _config()
    config.backend = "gcp"
    with pytest.raises(ValueError, match=r"requires shifter\.yaml backend: aws"):
        aws_eks._validate_config(config)


def test_validate_config_rejects_unsupported_profile():
    config = _config()
    config.deployment.profile = "staging"
    with pytest.raises(ValueError, match="supports only dev, proof, and prod"):
        aws_eks._validate_config(config)


def test_validate_terraform_inputs_rejects_missing_required_key(tmp_path):
    payload = _terraform_inputs()
    del payload["domain_name"]
    inputs = tmp_path / "eks.tfvars.json"
    inputs.write_text(json.dumps(payload), encoding="utf-8")
    config = _config()
    with pytest.raises(ValueError, match="input file is missing"):
        aws_eks._validate_terraform_inputs(inputs, config, allowed_roots=(tmp_path,))


def test_validate_terraform_inputs_rejects_region_mismatch(tmp_path):
    payload = _terraform_inputs()
    payload["aws_region"] = "us-west-2"  # shifter.yaml settings.region is us-east-2
    inputs = tmp_path / "eks.tfvars.json"
    inputs.write_text(json.dumps(payload), encoding="utf-8")
    config = _config()
    with pytest.raises(ValueError, match=r"region does not match shifter\.yaml"):
        aws_eks._validate_terraform_inputs(inputs, config, allowed_roots=(tmp_path,))


def test_validate_terraform_inputs_rejects_domain_mismatch(tmp_path):
    payload = _terraform_inputs()
    payload["domain_name"] = "attacker.example.net"  # shifter.yaml domain is shifter.example.com
    inputs = tmp_path / "eks.tfvars.json"
    inputs.write_text(json.dumps(payload), encoding="utf-8")
    config = _config()
    with pytest.raises(ValueError, match=r"domain does not match shifter\.yaml"):
        aws_eks._validate_terraform_inputs(inputs, config, allowed_roots=(tmp_path,))


def test_read_json_mapping_rejects_non_json_suffix(tmp_path):
    bad = tmp_path / "inputs.txt"
    bad.write_text("{}")
    with pytest.raises(ValueError, match=r"must use a \.json suffix"):
        aws_eks._read_json_mapping(bad, label="test input", allowed_roots=(tmp_path,))


def test_read_json_mapping_rejects_oversized_file(tmp_path):
    big = tmp_path / "big.json"
    big.write_text("x" * (aws_eks._MAX_PROTECTED_JSON_BYTES + 1))
    with pytest.raises(ValueError, match="exceeds the"):
        aws_eks._read_json_mapping(big, label="test input", allowed_roots=(tmp_path,))


def test_read_json_mapping_rejects_invalid_json(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{ not valid json")
    with pytest.raises(ValueError, match="must be valid JSON"):
        aws_eks._read_json_mapping(bad, label="test input", allowed_roots=(tmp_path,))


def test_read_json_mapping_rejects_non_object_payload(tmp_path):
    arr = tmp_path / "arr.json"
    arr.write_text("[1, 2, 3]")
    with pytest.raises(ValueError, match="must contain a JSON object"):
        aws_eks._read_json_mapping(arr, label="test input", allowed_roots=(tmp_path,))


def test_verify_effective_irsa_rejects_missing_probe_identity():
    roles = dict.fromkeys(aws_eks._IRSA_PROBE_IDENTITIES, "arn:aws:iam::123456789012:role/x")
    del roles["provisioner"]
    with pytest.raises(ValueError, match="missing IRSA probe identities"):
        aws_eks._verify_effective_irsa(roles, "repo@sha256:" + "a" * 64)


def test_verify_effective_irsa_rejects_non_string_role_arn():
    roles = dict.fromkeys(aws_eks._IRSA_PROBE_IDENTITIES, "arn:aws:iam::123456789012:role/x")
    roles["provisioner"] = 12345
    with pytest.raises(ValueError, match="must be strings"):
        aws_eks._verify_effective_irsa(roles, "repo@sha256:" + "a" * 64)


def test_cli_exposes_explicit_eks_commands_without_branch_inputs(monkeypatch):
    import cli

    parser = cli._build_parser()
    deploy = parser.parse_args(
        ["eks-deploy", "--config", "shifter.yaml", "--images", "images.json", "--profile", "operator"]
    )
    teardown = parser.parse_args(["eks-teardown", "--config", "shifter.yaml", "--profile", "operator"])

    assert deploy.command == "eks-deploy"
    assert teardown.command == "eks-teardown"
    assert not hasattr(deploy, "branch")
    assert not hasattr(teardown, "ref")


def test_aws_eks_module_import_does_not_depend_on_caller_cwd(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(Path(aws_eks.__file__).parent))
    sys.modules.pop("aws_eks", None)
    __import__("aws_eks")


def test_validated_runtime_env_allows_empty_optional_but_rejects_empty_required():
    # Optional keys (e.g. DC_DOMAIN_NAME with no Windows DC scenario) may be empty
    # by the Terraform contract; required keys must be present and non-empty.
    from installation.runtime_inventory_aws import AWS_EKS_REQUIRED_RUNTIME_ENV_KEYS

    base = {key: f"value-for-{key}" for key in AWS_EKS_REQUIRED_RUNTIME_ENV_KEYS}

    ok = {**base, "DC_DOMAIN_NAME": ""}
    result = aws_eks._validated_runtime_env({"runtime_env": {"value": ok}})
    assert result["DC_DOMAIN_NAME"] == ""

    bad = {**base, "AWS_REGION": ""}
    with pytest.raises(ValueError, match="must be non-empty"):
        aws_eks._validated_runtime_env({"runtime_env": {"value": bad}})


def test_populate_eks_workload_secrets_copies_sources_via_file(monkeypatch):
    # Copies the portal DB/app secrets into the empty eks-owned workload secrets,
    # moving values through file:// so the raw secret never lands on argv.
    calls: list[list[str]] = []

    def runner(cmd, **kwargs):
        calls.append(cmd)
        if "get-secret-value" in cmd:
            return SimpleNamespace(stdout='{"password":"supersecretvalue12345"}\n')
        return SimpleNamespace(stdout="")

    monkeypatch.setattr(aws_eks, "run_cmd", runner)
    aws_eks._populate_eks_workload_secrets(
        _terraform_outputs(), environment="dev", region="us-east-2", aws_profile=None
    )

    gets = [c for c in calls if "get-secret-value" in c]
    puts = [c for c in calls if "put-secret-value" in c]
    assert any("shifter-dev-portal-db-credentials" in c for c in gets)
    assert any("shifter-dev-portal-app" in c for c in gets)
    assert any("shifter-dev-portal-cognito" in c for c in gets)
    assert len(puts) == 3
    for cmd in puts:
        assert any(isinstance(a, str) and a.startswith("file://") for a in cmd)
        assert not any("supersecretvalue12345" in a for a in cmd)


def test_runtime_plugin_pool_labeler_follows_the_pool_toggle():
    """The trusted node-pool labeler (#2526) renders only with the plugin pool's node role."""
    disabled = aws_eks.render_aws_values(_config(), _terraform_outputs(), _images())
    assert disabled["runtimePluginPool"] == {"labeler": {"enabled": False, "nodeGroupAsg": ""}}
    assert "nodePoolLabeler" not in disabled["identity"]["serviceAccountRoleArns"]

    outputs = _terraform_outputs()
    labeler = "arn:aws:iam::123456789012:role/shifter-dev-node-pool-labeler"
    node_group = "eks-runtime-plugins-1234-abcd"
    outputs["workload_role_arns"]["value"]["nodePoolLabeler"] = labeler
    outputs["runtime_plugin_node_group_asg"] = {"value": node_group}
    enabled = aws_eks.render_aws_values(_config(), outputs, _images())
    assert enabled["runtimePluginPool"] == {"labeler": {"enabled": True, "nodeGroupAsg": node_group}}
    assert enabled["identity"]["serviceAccountRoleArns"]["nodePoolLabeler"] == labeler

    # Exactly one of the identity and the pool role means a misconfigured environment.
    del outputs["runtime_plugin_node_group_asg"]
    with pytest.raises(ValueError, match="enabled together"):
        aws_eks.render_aws_values(_config(), outputs, _images())
    pool_only = _terraform_outputs()
    pool_only["runtime_plugin_node_group_asg"] = {"value": node_group}
    with pytest.raises(ValueError, match="enabled together"):
        aws_eks.render_aws_values(_config(), pool_only, _images())


def test_feature_artifact_acquisition_is_enabled_only_by_the_acquirer_identity(monkeypatch):
    """The artifactAcquirer role enables acquisition Jobs (#2463); without it they stay off."""
    disabled = aws_eks.render_aws_values(_config(), _terraform_outputs(), _images())
    assert disabled["capabilities"]["featureArtifactAcquisition"] is False
    assert disabled["runtimeEnv"]["FEATURE_ARTIFACT_JOB_IMAGE"] == ""
    assert "artifactAcquirer" not in disabled["identity"]["serviceAccountRoleArns"]

    outputs = _terraform_outputs()
    acquirer = "arn:aws:iam::123456789012:role/shifter-dev-artifact-acquirer"
    outputs["workload_role_arns"]["value"]["artifactAcquirer"] = acquirer
    enabled = aws_eks.render_aws_values(_config(), outputs, _images())
    assert enabled["capabilities"]["featureArtifactAcquisition"] is True
    assert enabled["runtimeEnv"]["FEATURE_ARTIFACT_JOB_IMAGE"] == _images()["platform"]
    assert enabled["identity"]["serviceAccountRoleArns"]["artifactAcquirer"] == acquirer

    images = _images()
    images.pop("platform")
    with pytest.raises(ValueError, match="platform"):
        aws_eks.render_aws_values(_config(), outputs, images)

    probed: list[tuple[str, str]] = []

    def runner(cmd, **_kwargs):
        if cmd[:3] == ["kubectl", "apply", "-f"]:
            manifest = json.loads(Path(cmd[3]).read_text())
            probed.append((manifest["metadata"]["namespace"], manifest["spec"]["serviceAccountName"]))
            runner.identity = manifest["metadata"]["labels"]["shifter.dev/irsa-check"]
        if cmd[:2] == ["kubectl", "logs"]:
            return SimpleNamespace(stdout=f"IRSA_OK:{runner.identity}\n")
        return SimpleNamespace(stdout="")

    monkeypatch.setattr(aws_eks, "run_cmd", runner)
    aws_eks._verify_effective_irsa(outputs["workload_role_arns"]["value"], _images()["platform"])
    assert ("shifter-acquisition", "artifact-acquirer") in probed
