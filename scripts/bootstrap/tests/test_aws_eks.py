"""Behavioral tests for the explicit AWS EKS/Helm bundle lifecycle."""

from __future__ import annotations

import json
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


def _terraform_outputs() -> dict[str, object]:
    return {
        "cluster_name": {"value": "shifter-dev-eks"},
        "cluster_access_role_arn": {"value": "arn:aws:iam::123456789012:role/shifter-dev-eks-deployer"},
        "certificate_arn": {"value": "arn:aws:acm:us-east-2:123456789012:certificate/example"},
        "waf_acl_arn": {"value": "arn:aws:wafv2:us-east-2:123456789012:regional/webacl/example/id"},
        "workload_role_arns": {
            "value": {
                "portal": "arn:aws:iam::123456789012:role/shifter-dev-portal",
                "workers": "arn:aws:iam::123456789012:role/shifter-dev-workers",
                "ctfScheduler": "arn:aws:iam::123456789012:role/shifter-dev-ctf-scheduler",
                "ingress": "arn:aws:iam::123456789012:role/shifter-dev-ingress",
                "cni": "arn:aws:iam::123456789012:role/shifter-dev-cni",
                "ebs-csi": "arn:aws:iam::123456789012:role/shifter-dev-ebs-csi",
                "efs-csi": "arn:aws:iam::123456789012:role/shifter-dev-efs-csi",
                "provisionerLauncher": "arn:aws:iam::123456789012:role/shifter-dev-provisioner-launcher",
                "provisioner": "arn:aws:iam::123456789012:role/shifter-dev-provisioner",
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
    assert values["identity"]["serviceAccountRoleArns"]["portal"].endswith("shifter-dev-portal")
    assert values["identity"]["serviceAccountRoleArns"]["workers"].endswith("shifter-dev-workers")
    assert values["identity"]["serviceAccountRoleArns"]["ctfScheduler"].endswith("shifter-dev-ctf-scheduler")
    assert values["runtimeEnv"]["CLOUD_PROVIDER"] == "aws"
    assert values["runtimeEnv"]["ENVIRONMENT"] == "development"
    assert values["runtimeEnv"]["AUTH_PROVIDER"] == "oidc"
    # ENGINE_TASK_IMAGE is renderer-generated from the attested provisioner digest.
    assert values["runtimeEnv"]["ENGINE_TASK_IMAGE"].endswith("engine-provisioner@sha256:" + ("a" * 64))
    # Provisioner env assembled by Terraform flows through the merged output.
    assert values["runtimeEnv"]["RANGE_VPC_ID"] == "vpc-xxxxxxxxxxxxxxxxx"
    assert values["runtimeEnv"]["QUEUE_ENGINE_CONSUMER_ID"].endswith("/engine")
    assert values["runtimeEnv"]["OIDC_SECRET_ID"] == "shifter/dev/cognito"
    assert values["runtime"]["secretReferences"] == {
        "app": "shifter/dev/app",
        "database": "shifter/dev/db",
    }
    rendered = json.dumps(values)
    assert "@sha256:" in rendered
    assert "SECRET_KEY=" not in rendered
    assert "PASSWORD=" not in rendered


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
            roles[name] for name in sorted(roles) if name != identity
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
    secret_stdin_calls: list[tuple[list[str], str]] = []
    result = SimpleNamespace(stdout=json.dumps(_terraform_outputs()))
    runner = Mock(side_effect=lambda cmd, **kwargs: calls.append(cmd) or result)
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
    assert any(cmd[:3] == ["aws", "eks", "update-kubeconfig"] and "--role-arn" in cmd for cmd in calls)
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
    assert sum(cmd[:3] == ["kubectl", "apply", "-f"] for cmd in calls) == 2
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
    assert len(secret_stdin_calls) == 3
    assert all('"secretReferences"' in values for _cmd, values in secret_stdin_calls)
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
