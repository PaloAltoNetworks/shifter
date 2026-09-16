"""Explicit AWS EKS lifecycle owner for the root-configured AWS bundle.

The platform control plane is Terraform-owned infrastructure plus the single
provider-neutral Helm chart. ECS remains a separate range-task transport and is
never read, imported, adopted, or destroyed by this module.
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path

from bootstrap_core import get_repo_root, run_cmd, run_cmd_secret_stdin
from preflight import Cloud, Mode, preflight_gate

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SHIFTER_PACKAGE_ROOT = _REPO_ROOT / "shifter"
if str(_SHIFTER_PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SHIFTER_PACKAGE_ROOT))

from installation.loader import load_root_config  # noqa: E402
from installation.render import (  # noqa: E402
    render_mission_control_lease_env,
    render_model_access_env,
)
from installation.runtime_inventory import (  # noqa: E402
    AWS_EKS_REQUIRED_RUNTIME_ENV_KEYS,
    AWS_RENDERER_OWNED_RUNTIME_ENV_KEYS,
)
from installation.schema import RootConfig  # noqa: E402

_LOWERCASE_HEX = frozenset("0123456789abcdef")
_EKS_NAMESPACE = "shifter-system"
_HELM_RELEASE = "shifter"
_LOAD_BALANCER_CONTROLLER_CHART_VERSION = "3.2.2"
# Pinned cluster-autoscaler chart (#1826). The image tag must track the cluster's
# Kubernetes minor; the chart's autoDiscovery + the node-group ASG discovery tags
# (k8s.io/cluster-autoscaler/<cluster>) let it manage only this cluster's ASG.
_CLUSTER_AUTOSCALER_CHART_VERSION = "9.37.0"
_MAX_PROTECTED_JSON_BYTES = 1024 * 1024
_TERRAFORM_NONINTERACTIVE = "-input=false"
_KUBECTL_TIMEOUT = "--timeout=5m"
_KUBECTL_IGNORE_NOT_FOUND = "--ignore-not-found=true"
_KUBECTL_NO_WAIT = "--wait=false"
_PLATFORM_NAMESPACES = {
    "shifter-platform": "control",
    "shifter-jobs": "jobs",
}
_MANAGED_ADDONS = (
    "vpc-cni",
    "aws-ebs-csi-driver",
    "aws-efs-csi-driver",
    "coredns",
    "kube-proxy",
    "aws-secrets-store-csi-driver-provider",
)
_IRSA_PROBE_IDENTITIES = {
    "cni": ("kube-system", "aws-node"),
    "ingress": ("kube-system", "aws-load-balancer-controller"),
    "ebs-csi": ("kube-system", "ebs-csi-controller-sa"),
    "efs-csi": ("kube-system", "efs-csi-controller-sa"),
    "cluster-autoscaler": ("kube-system", "cluster-autoscaler"),
    "portal": ("shifter-platform", "portal"),
    "workers": ("shifter-platform", "workers"),
    "ctfScheduler": ("shifter-platform", "ctf-scheduler"),
    "provisionerLauncher": ("shifter-platform", "provisioner-launcher"),
    "provisioner": ("shifter-jobs", "provisioner"),
}
_IRSA_PROBE_SCRIPT = """import json, os
import boto3
from botocore.exceptions import ClientError

identity = os.environ["SHIFTER_IRSA_IDENTITY"]
expected_role = os.environ["SHIFTER_EXPECTED_ROLE_ARN"]
caller_arn = boto3.client("sts").get_caller_identity()["Arn"]
role_name = expected_role.rsplit("/", 1)[-1]
if f"/{role_name}/" not in caller_arn:
    raise RuntimeError("the diagnostic pod did not receive its expected role")

token_path = os.environ["AWS_WEB_IDENTITY_TOKEN_FILE"]
with open(token_path, encoding="utf-8") as token_file:
    token = token_file.read()
for other_role in json.loads(os.environ["SHIFTER_SIBLING_ROLE_ARNS"]):
    try:
        boto3.client("sts").assume_role_with_web_identity(
            RoleArn=other_role,
            RoleSessionName="shifter-irsa-negative-check",
            WebIdentityToken=token,
        )
    except ClientError:
        continue
    raise RuntimeError("the projected token assumed a sibling workload role")
print(f"IRSA_OK:{identity}")
"""
# Chart service accounts that receive an IRSA role-arn annotation (#1826 adds the
# provisioner Job launcher + the privileged provisioner). The add-on controller
# roles (cni, ingress, ebs-csi, efs-csi, cluster-autoscaler) are wired to their
# controllers directly (EKS add-on service_account_role_arn / Helm SA annotation),
# not projected into the chart's identity.serviceAccountRoleArns.
_WORKLOAD_ROLE_KEYS = frozenset({"portal", "workers", "ctfScheduler", "provisionerLauncher", "provisioner"})
# Single source of truth in the installation package (installation.runtime_inventory_aws),
# so the renderer and the backend bundle's generated-output projection cannot drift.
_RENDERER_OWNED_RUNTIME_ENV = AWS_RENDERER_OWNED_RUNTIME_ENV_KEYS
_REQUIRED_TERRAFORM_INPUTS = frozenset(
    {
        "addon_versions",
        "aws_region",
        "deployment_role_arn",
        "domain_name",
        "edge_client_cidrs",
        "provider_api_cidrs",
        "runtime_env",
    }
)


def eks_root(profile: str) -> Path:
    """Return the isolated Terraform root for an EKS profile."""
    if profile not in {"dev", "proof", "prod"}:
        raise ValueError(f"unsupported AWS EKS profile {profile!r}")
    return get_repo_root() / "platform" / "terraform" / "environments" / profile / "eks"


def _output(outputs: Mapping[str, object], name: str) -> object:
    """Return a required value from Terraform's JSON output envelope."""
    raw = outputs.get(name)
    if not isinstance(raw, Mapping) or "value" not in raw:
        raise ValueError(f"missing required EKS Terraform output {name!r}")
    return raw["value"]


def _validate_config(config: RootConfig) -> None:
    """Require the AWS backend and an EKS-supported deployment profile."""
    if config.backend != "aws":
        raise ValueError("the EKS lifecycle requires shifter.yaml backend: aws")
    if config.deployment.profile not in {"dev", "proof", "prod"}:
        raise ValueError("the AWS EKS bundle supports only dev, proof, and prod profiles")


def _validated_images(images: Mapping[str, object]) -> dict[str, str]:
    """Return image identities after enforcing digest-pinned references."""
    if not images:
        raise ValueError("at least one attested image identity is required")
    validated: dict[str, str] = {}
    for name, identity in images.items():
        if not isinstance(name, str) or not isinstance(identity, str) or not _is_attested_image_identity(identity):
            raise ValueError(f"image {name!r} must be an exact repository@sha256:<64 lowercase hex> identity")
        validated[name] = identity
    return validated


def _is_attested_image_identity(identity: str) -> bool:
    """Validate a digest-pinned image identity in linear time."""
    repository, separator, digest = identity.rpartition("@sha256:")
    repository_parts = repository.replace(":", "/").split("/")
    return bool(
        separator
        and repository_parts
        and all(repository_parts)
        and all(not character.isspace() and character != "@" for character in repository)
        and len(digest) == 64
        and all(character in _LOWERCASE_HEX for character in digest)
    )


def _run_helm_with_values(command: list[str], values: Mapping[str, object]) -> None:
    """Stream rendered values to Helm so secret references never touch disk."""
    return_code = run_cmd_secret_stdin(
        [*command, "--values", "-"],
        secret_stdin=json.dumps(values, sort_keys=True),
    )
    if return_code != 0:
        raise RuntimeError(f"Helm command failed with exit code {return_code}")


def _cidr_output(outputs: Mapping[str, object], name: str) -> list[str]:
    """Return a required Terraform output containing only CIDR strings."""
    values = _output(outputs, name)
    if not isinstance(values, list) or not all(isinstance(value, str) and value for value in values):
        raise ValueError(f"EKS Terraform output {name!r} must be a list of CIDR strings")
    return values


def _runtime_environment(profile: str) -> str:
    """Map the deployment profile to the Django runtime environment."""
    return {"dev": "development", "prod": "production"}.get(profile, profile)


def _runtime_env(config: RootConfig, outputs: Mapping[str, object]) -> dict[str, str]:
    """Build the complete canonical runtime environment for AWS EKS."""
    raw = _output(outputs, "runtime_env")
    if not isinstance(raw, Mapping) or not all(
        isinstance(key, str) and isinstance(value, str) and value for key, value in raw.items()
    ):
        raise ValueError("runtime_env must map canonical runtime keys to non-empty string values")
    conflicting = sorted(_RENDERER_OWNED_RUNTIME_ENV.intersection(raw))
    if conflicting:
        raise ValueError("runtime_env must not override renderer-owned keys: " + ", ".join(conflicting))
    missing = sorted(AWS_EKS_REQUIRED_RUNTIME_ENV_KEYS.difference(raw))
    if missing:
        raise ValueError("runtime_env is missing required keys: " + ", ".join(missing))
    domain = config.deployment.domain
    model_access_env = {}
    for line in render_model_access_env(config).splitlines():
        key, value = line.split("=", 1)
        model_access_env[key] = value
    mission_control_lease_env = {}
    for line in render_mission_control_lease_env(config).splitlines():
        key, value = line.split("=", 1)
        mission_control_lease_env[key] = value
    return {
        **dict(raw),
        "AUTH_PROVIDER": "oidc",
        "CLOUD_PROVIDER": "aws",
        "DJANGO_ALLOWED_HOSTS": f"{domain},localhost,127.0.0.1",
        "DJANGO_CSRF_TRUSTED_ORIGINS": f"https://{domain}",
        "ENVIRONMENT": _runtime_environment(config.deployment.profile),
        **model_access_env,
        **mission_control_lease_env,
        "SITE_URL": f"https://{domain}",
    }


def _protected_input_roots() -> tuple[Path, ...]:
    """Return the explicit roots from which protected deploy inputs may be read."""
    candidates = {
        get_repo_root(),
        Path(tempfile.gettempdir()),
    }
    for variable in ("RUNNER_TEMP", "SHIFTER_PROTECTED_INPUT_ROOT"):
        configured = os.environ.get(variable)
        if configured:
            candidates.add(Path(configured).expanduser())
    return tuple(candidate.resolve() for candidate in candidates)


def _required_file(
    path: str | Path | None,
    *,
    label: str,
    allowed_roots: tuple[Path, ...],
) -> Path:
    """Resolve a regular input file and enforce its protected-root boundary."""
    if path is None or not str(path).strip():
        raise ValueError(f"{label} is required")
    candidate = Path(path).expanduser()
    if candidate.is_symlink():
        raise ValueError(f"{label} must not be a symbolic link")
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"{label} does not exist") from exc
    if not resolved.is_file():
        raise ValueError(f"{label} does not exist")
    if not any(resolved.is_relative_to(root) for root in allowed_roots):
        roots = ", ".join(str(root) for root in allowed_roots)
        raise ValueError(f"{label} must be inside an approved protected-input root: {roots}")
    return resolved


def _read_json_mapping(
    path: str | Path | None,
    *,
    label: str,
    allowed_roots: tuple[Path, ...],
) -> tuple[Path, dict[str, object]]:
    """Read a bounded JSON object from an approved protected-input root."""
    resolved = _required_file(path, label=label, allowed_roots=allowed_roots)
    if not any(resolved.is_relative_to(root) for root in allowed_roots):
        raise ValueError(f"{label} escaped its approved protected-input roots")
    if resolved.suffix != ".json":
        raise ValueError(f"{label} must use a .json suffix")
    if resolved.stat().st_size > _MAX_PROTECTED_JSON_BYTES:
        raise ValueError(f"{label} exceeds the {_MAX_PROTECTED_JSON_BYTES}-byte limit")
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return resolved, payload


def _validate_terraform_inputs(
    path: str | Path | None,
    config: RootConfig,
    *,
    allowed_roots: tuple[Path, ...],
) -> Path:
    """Validate the protected Terraform projection and return its safe path."""
    resolved, payload = _read_json_mapping(
        path,
        label="EKS Terraform input file",
        allowed_roots=allowed_roots,
    )
    missing = sorted(_REQUIRED_TERRAFORM_INPUTS.difference(payload))
    if missing:
        raise ValueError("the protected EKS Terraform input file is missing: " + ", ".join(missing))
    if payload["aws_region"] != config.settings["region"]:
        raise ValueError("the protected EKS Terraform input region does not match shifter.yaml")
    if payload["domain_name"] != config.deployment.domain:
        raise ValueError("the protected EKS Terraform input domain does not match shifter.yaml")
    return resolved


def _apply_platform_namespaces() -> None:
    """Create the restricted platform namespaces the chart deploys into."""
    with tempfile.TemporaryDirectory(prefix="shifter-eks-bootstrap-") as staging:
        staging_path = Path(staging)
        for namespace, plane in _PLATFORM_NAMESPACES.items():
            manifest = {
                "apiVersion": "v1",
                "kind": "Namespace",
                "metadata": {
                    "name": namespace,
                    "labels": {
                        "app.kubernetes.io/part-of": "shifter",
                        "shifter.dev/plane": plane,
                        "pod-security.kubernetes.io/audit": "restricted",
                        "pod-security.kubernetes.io/enforce": "restricted",
                        "pod-security.kubernetes.io/warn": "restricted",
                    },
                },
            }
            manifest_path = staging_path / f"{namespace}.json"
            manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
            run_cmd(["kubectl", "apply", "-f", str(manifest_path)])


def _install_load_balancer_controller(cluster_name: str, role_arn: str) -> None:
    """Install the AWS load-balancer controller bound to its exact IRSA role."""
    run_cmd(["helm", "repo", "add", "eks", "https://aws.github.io/eks-charts", "--force-update"])
    run_cmd(["helm", "repo", "update", "eks"])
    run_cmd(
        [
            "helm",
            "upgrade",
            "--install",
            "aws-load-balancer-controller",
            "eks/aws-load-balancer-controller",
            "--namespace",
            "kube-system",
            "--version",
            _LOAD_BALANCER_CONTROLLER_CHART_VERSION,
            "--set-string",
            f"clusterName={cluster_name}",
            "--set",
            "serviceAccount.create=true",
            "--set-string",
            "serviceAccount.name=aws-load-balancer-controller",
            "--set-string",
            "serviceAccount.annotations.eks\\.amazonaws\\.com/role-arn=" + role_arn,
            "--atomic",
            "--wait",
            "--timeout",
            "10m",
        ]
    )
    run_cmd(
        [
            "kubectl",
            "rollout",
            "status",
            "deployment/aws-load-balancer-controller",
            "--namespace",
            "kube-system",
            _KUBECTL_TIMEOUT,
        ]
    )


def _install_cluster_autoscaler(cluster_name: str, region: str, role_arn: str) -> None:
    """Install the cluster-autoscaler scoped to this cluster's ASG (#1826).

    autoDiscovery.clusterName plus the node-group discovery tags applied in
    Terraform keep it from touching another cluster's capacity.
    """
    run_cmd(["helm", "repo", "add", "autoscaler", "https://kubernetes.github.io/autoscaler", "--force-update"])
    run_cmd(["helm", "repo", "update", "autoscaler"])
    run_cmd(
        [
            "helm",
            "upgrade",
            "--install",
            "cluster-autoscaler",
            "autoscaler/cluster-autoscaler",
            "--namespace",
            "kube-system",
            "--version",
            _CLUSTER_AUTOSCALER_CHART_VERSION,
            "--set-string",
            f"autoDiscovery.clusterName={cluster_name}",
            "--set-string",
            f"awsRegion={region}",
            "--set",
            "rbac.serviceAccount.create=true",
            "--set-string",
            "rbac.serviceAccount.name=cluster-autoscaler",
            "--set-string",
            "rbac.serviceAccount.annotations.eks\\.amazonaws\\.com/role-arn=" + role_arn,
            # Only scale ASGs this cluster owns, and let the autoscaler evict
            # pods without the restrictive system-pod guard blocking scale-down.
            "--set",
            "extraArgs.balance-similar-node-groups=true",
            "--set",
            "extraArgs.skip-nodes-with-system-pods=false",
            "--atomic",
            "--wait",
            "--timeout",
            "10m",
        ]
    )
    run_cmd(
        [
            "kubectl",
            "rollout",
            "status",
            "deployment/cluster-autoscaler-aws-cluster-autoscaler",
            "--namespace",
            "kube-system",
            _KUBECTL_TIMEOUT,
        ]
    )


def _bootstrap_cluster(outputs: Mapping[str, object], region: str) -> None:
    """Create platform namespaces and install the cluster-scoped controllers.

    The AWS load-balancer controller (ALB ingress) and the cluster-autoscaler
    (#1826) each bind to their exact IRSA role via a service-account role-arn
    annotation.
    """
    roles = _output(outputs, "workload_role_arns")
    if not isinstance(roles, Mapping) or not isinstance(roles.get("ingress"), str):
        raise ValueError("workload_role_arns must include the ingress controller role")
    if not isinstance(roles.get("cluster-autoscaler"), str):
        raise ValueError("workload_role_arns must include the cluster-autoscaler role")
    cluster_name = str(_output(outputs, "cluster_name"))
    _apply_platform_namespaces()
    _install_load_balancer_controller(cluster_name, str(roles["ingress"]))
    _install_cluster_autoscaler(cluster_name, region, str(roles["cluster-autoscaler"]))


def _wait_for_managed_addons(cluster_name: str, *, aws_profile: str | None) -> None:
    """Fail closed unless every Terraform-owned managed add-on is ACTIVE."""
    for addon_name in _MANAGED_ADDONS:
        run_cmd(
            [
                "aws",
                "eks",
                "wait",
                "addon-active",
                "--cluster-name",
                cluster_name,
                "--addon-name",
                addon_name,
            ],
            profile=aws_profile,
        )


def _verify_effective_irsa(roles: Mapping[str, object], platform_image: str) -> None:
    """Prove exact effective IRSA and sibling-role denial without exposing tokens."""
    missing = sorted(set(_IRSA_PROBE_IDENTITIES).difference(roles))
    if missing:
        raise ValueError("workload_role_arns is missing IRSA probe identities: " + ", ".join(missing))
    if not all(isinstance(roles[name], str) for name in _IRSA_PROBE_IDENTITIES):
        raise ValueError("IRSA probe role ARNs must be strings")

    role_arns = {name: str(roles[name]) for name in _IRSA_PROBE_IDENTITIES}
    with tempfile.TemporaryDirectory(prefix="shifter-irsa-readiness-") as staging:
        staging_path = Path(staging)
        for identity, (namespace, service_account) in _IRSA_PROBE_IDENTITIES.items():
            pod_name = "shifter-irsa-check-" + re.sub(r"[^a-z0-9-]", "-", identity.lower())
            sibling_roles = [role_arns[name] for name in sorted(role_arns) if name != identity]
            manifest = {
                "apiVersion": "v1",
                "kind": "Pod",
                "metadata": {
                    "name": pod_name,
                    "namespace": namespace,
                    "labels": {
                        "app.kubernetes.io/name": "shifter-irsa-readiness",
                        "shifter.dev/irsa-check": identity,
                    },
                },
                "spec": {
                    "serviceAccountName": service_account,
                    "automountServiceAccountToken": True,
                    "restartPolicy": "Never",
                    "securityContext": {
                        "runAsNonRoot": True,
                        "runAsUser": 1000,
                        "runAsGroup": 1000,
                        "seccompProfile": {"type": "RuntimeDefault"},
                    },
                    "containers": [
                        {
                            "name": "irsa-check",
                            "image": platform_image,
                            "imagePullPolicy": "IfNotPresent",
                            "command": ["python", "-c", _IRSA_PROBE_SCRIPT],
                            "env": [
                                {"name": "SHIFTER_IRSA_IDENTITY", "value": identity},
                                {"name": "SHIFTER_EXPECTED_ROLE_ARN", "value": role_arns[identity]},
                                {"name": "SHIFTER_SIBLING_ROLE_ARNS", "value": json.dumps(sibling_roles)},
                            ],
                            "resources": {
                                "requests": {"cpu": "25m", "memory": "64Mi"},
                                "limits": {"cpu": "250m", "memory": "256Mi"},
                            },
                            "securityContext": {
                                "allowPrivilegeEscalation": False,
                                "capabilities": {"drop": ["ALL"]},
                                "readOnlyRootFilesystem": True,
                            },
                        }
                    ],
                },
            }
            manifest_path = staging_path / f"{pod_name}.json"
            manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
            try:
                run_cmd(["kubectl", "apply", "-f", str(manifest_path)])
                run_cmd(
                    [
                        "kubectl",
                        "wait",
                        f"pod/{pod_name}",
                        "--namespace",
                        namespace,
                        "--for=jsonpath={.status.phase}=Succeeded",
                        _KUBECTL_TIMEOUT,
                    ]
                )
                result = run_cmd(["kubectl", "logs", pod_name, "--namespace", namespace], capture=True)
                if getattr(result, "stdout", "").strip() != f"IRSA_OK:{identity}":
                    raise RuntimeError(f"effective IRSA readiness failed for {identity}")
            finally:
                run_cmd(
                    [
                        "kubectl",
                        "delete",
                        "pod",
                        pod_name,
                        "--namespace",
                        namespace,
                        _KUBECTL_IGNORE_NOT_FOUND,
                        _KUBECTL_NO_WAIT,
                    ]
                )


def _restricted_probe_container(platform_image: str, workload: str) -> dict[str, object]:
    """Build a restricted container that records denied API egress."""
    marker_path = "/var/run/shifter-readiness/networkpolicy-ok"
    success_action = (
        f'Path("{marker_path}").touch()\ntime.sleep(300)' if workload == "deployment" else "raise SystemExit(0)"
    )
    script = f"""import socket, time
from pathlib import Path
try:
    connection = socket.create_connection(("kubernetes.default.svc", 443), timeout=5)
except OSError:
    print("NETWORK_POLICY_OK:{workload}", flush=True)
    {success_action}
else:
    connection.close()
    raise RuntimeError("default-deny NetworkPolicy allowed Kubernetes API access")
"""
    container: dict[str, object] = {
        "name": "networkpolicy-check",
        "image": platform_image,
        "imagePullPolicy": "IfNotPresent",
        "command": ["python", "-c", script],
        "resources": {
            "requests": {"cpu": "25m", "memory": "32Mi"},
            "limits": {"cpu": "100m", "memory": "128Mi"},
        },
        "securityContext": {
            "allowPrivilegeEscalation": False,
            "capabilities": {"drop": ["ALL"]},
            "readOnlyRootFilesystem": True,
            "runAsNonRoot": True,
            "runAsUser": 1000,
        },
    }
    if workload == "deployment":
        container.update(
            {
                "readinessProbe": {
                    "exec": {"command": ["test", "-f", marker_path]},
                    "periodSeconds": 1,
                    "timeoutSeconds": 1,
                    "failureThreshold": 300,
                },
                "volumeMounts": [{"name": "readiness", "mountPath": "/var/run/shifter-readiness"}],
            }
        )
    return container


def _assert_admission_policy_fail_closed() -> None:
    """Require the provisioner admission policy and binding to deny failures."""
    policy = run_cmd(
        [
            "kubectl",
            "get",
            "validatingadmissionpolicy",
            "restrict-provisioner-jobs",
            "-o",
            "jsonpath={.spec.failurePolicy}",
        ],
        capture=True,
    )
    binding = run_cmd(
        [
            "kubectl",
            "get",
            "validatingadmissionpolicybinding",
            "restrict-provisioner-jobs",
            "-o",
            "jsonpath={.spec.validationActions[0]}",
        ],
        capture=True,
    )
    if getattr(policy, "stdout", "").strip() != "Fail" or getattr(binding, "stdout", "").strip() != "Deny":
        raise RuntimeError("provisioner admission policy is not active in fail-closed deny mode")


def _networkpolicy_probe_manifests(
    platform_image: str,
) -> tuple[str, str, dict[str, object], dict[str, object], dict[str, object]]:
    """Build the valid readiness workloads and invalid admission probe."""
    deployment_name = "shifter-networkpolicy-deployment"
    job_name = "shifter-networkpolicy-job"
    pod_security_context = {
        "runAsNonRoot": True,
        "runAsUser": 1000,
        "runAsGroup": 1000,
        "seccompProfile": {"type": "RuntimeDefault"},
    }
    labels = {
        "app.kubernetes.io/name": "shifter-networkpolicy-readiness",
        "shifter.dev/readiness-check": "networkpolicy",
    }
    deployment = {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": deployment_name, "namespace": "shifter-platform"},
        "spec": {
            "replicas": 1,
            "selector": {"matchLabels": labels},
            "template": {
                "metadata": {"labels": labels},
                "spec": {
                    "automountServiceAccountToken": False,
                    "securityContext": pod_security_context,
                    "containers": [_restricted_probe_container(platform_image, "deployment")],
                    "volumes": [{"name": "readiness", "emptyDir": {}}],
                },
            },
        },
    }
    job = {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {"name": job_name, "namespace": "shifter-jobs"},
        "spec": {
            "backoffLimit": 0,
            "template": {
                "metadata": {"labels": labels},
                "spec": {
                    "automountServiceAccountToken": False,
                    "restartPolicy": "Never",
                    "securityContext": pod_security_context,
                    "containers": [_restricted_probe_container(platform_image, "job")],
                },
            },
        },
    }
    rejected_job = {
        **job,
        "metadata": {"name": "shifter-admission-denial-check", "namespace": "shifter-jobs"},
        "spec": {
            **job["spec"],
            "template": {
                **job["spec"]["template"],
                "spec": {
                    **job["spec"]["template"]["spec"],
                    "serviceAccountName": "provisioner",
                },
            },
        },
    }
    return deployment_name, job_name, deployment, job, rejected_job


def _run_networkpolicy_readiness_probes(
    deployment_name: str,
    job_name: str,
    deployment: Mapping[str, object],
    job: Mapping[str, object],
    rejected_job: Mapping[str, object],
) -> None:
    """Apply the probes and require admission and network denial evidence."""
    with tempfile.TemporaryDirectory(prefix="shifter-k8s-readiness-") as staging:
        staging_path = Path(staging)
        deployment_path = staging_path / "deployment.json"
        job_path = staging_path / "job.json"
        deployment_path.write_text(json.dumps(deployment, sort_keys=True), encoding="utf-8")
        job_path.write_text(json.dumps(job, sort_keys=True), encoding="utf-8")
        try:
            rejection_code = run_cmd_secret_stdin(
                ["kubectl", "create", "--dry-run=server", "-f", "-"],
                secret_stdin=json.dumps(rejected_job, sort_keys=True),
            )
            if rejection_code == 0:
                raise RuntimeError("provisioner admission policy admitted a non-launcher Job")

            run_cmd(["kubectl", "apply", "-f", str(deployment_path)])
            run_cmd(["kubectl", "apply", "-f", str(job_path)])
            run_cmd(
                [
                    "kubectl",
                    "rollout",
                    "status",
                    f"deployment/{deployment_name}",
                    "--namespace",
                    "shifter-platform",
                    _KUBECTL_TIMEOUT,
                ]
            )
            run_cmd(
                [
                    "kubectl",
                    "wait",
                    f"job/{job_name}",
                    "--namespace",
                    "shifter-jobs",
                    "--for=condition=complete",
                    _KUBECTL_TIMEOUT,
                ]
            )
            for resource, namespace, expected in (
                (f"deployment/{deployment_name}", "shifter-platform", "NETWORK_POLICY_OK:deployment"),
                (f"job/{job_name}", "shifter-jobs", "NETWORK_POLICY_OK:job"),
            ):
                result = run_cmd(["kubectl", "logs", resource, "--namespace", namespace], capture=True)
                if getattr(result, "stdout", "").strip() != expected:
                    raise RuntimeError(f"NetworkPolicy readiness failed for {resource.split('/', 1)[0]}")
        finally:
            run_cmd(
                [
                    "kubectl",
                    "delete",
                    "deployment",
                    deployment_name,
                    "--namespace",
                    "shifter-platform",
                    _KUBECTL_IGNORE_NOT_FOUND,
                    _KUBECTL_NO_WAIT,
                ]
            )
            run_cmd(
                [
                    "kubectl",
                    "delete",
                    "job",
                    job_name,
                    "--namespace",
                    "shifter-jobs",
                    _KUBECTL_IGNORE_NOT_FOUND,
                    _KUBECTL_NO_WAIT,
                ]
            )


def _verify_kubernetes_security_enforcement(platform_image: str) -> None:
    """Prove admission denial and strict NetworkPolicy on Deployment and Job pods."""
    _assert_admission_policy_fail_closed()
    probes = _networkpolicy_probe_manifests(platform_image)
    _run_networkpolicy_readiness_probes(*probes)


def render_aws_values(
    config: RootConfig,
    terraform_outputs: Mapping[str, object],
    images: Mapping[str, object],
) -> dict[str, object]:
    """Render non-secret AWS values from validated config, outputs, and digests."""
    _validate_config(config)
    roles = _output(terraform_outputs, "workload_role_arns")
    if not isinstance(roles, Mapping) or not all(isinstance(k, str) and isinstance(v, str) for k, v in roles.items()):
        raise ValueError("workload_role_arns must map exact service-account names to IAM role ARNs")
    missing_roles = sorted(_WORKLOAD_ROLE_KEYS.difference(roles))
    if missing_roles:
        raise ValueError("workload_role_arns is missing chart workload roles: " + ", ".join(missing_roles))
    validated_images = _validated_images(images)
    if "provisioner" not in validated_images:
        raise ValueError("images must include a digest-pinned 'provisioner' identity for the Kubernetes Job launcher")
    # ENGINE_TASK_IMAGE is the provisioner Job image; the launcher resolves it
    # from the runtime env. It is renderer-generated from the attested digest,
    # mirroring GCP's render_runtime_env.py.
    runtime_env = _runtime_env(config, terraform_outputs)
    runtime_env["ENGINE_TASK_IMAGE"] = validated_images["provisioner"]
    edge_client_cidrs = _cidr_output(terraform_outputs, "edge_client_cidrs")
    return {
        "provider": {"name": "aws"},
        "deployment": {"name": config.deployment.name, "profile": config.deployment.profile},
        "capabilities": {"kubernetesJobLauncher": True},
        "provisioner": {"taskRunner": "aws"},
        "edge": {
            "hostname": config.deployment.domain,
            "certificateArn": _output(terraform_outputs, "certificate_arn"),
            "wafAclArn": _output(terraform_outputs, "waf_acl_arn"),
            "ingress": {
                "enabled": True,
                "className": "alb",
                "annotations": {
                    "alb.ingress.kubernetes.io/scheme": "internet-facing",
                    "alb.ingress.kubernetes.io/target-type": "ip",
                    "alb.ingress.kubernetes.io/listen-ports": '[{"HTTPS":443}]',
                    "alb.ingress.kubernetes.io/ssl-redirect": "443",
                    "alb.ingress.kubernetes.io/load-balancer-name": (
                        f"{_output(terraform_outputs, 'cluster_name')}-platform"
                    ),
                    "alb.ingress.kubernetes.io/certificate-arn": _output(terraform_outputs, "certificate_arn"),
                    "alb.ingress.kubernetes.io/wafv2-acl-arn": _output(terraform_outputs, "waf_acl_arn"),
                    "alb.ingress.kubernetes.io/inbound-cidrs": ",".join(edge_client_cidrs),
                },
                "host": config.deployment.domain,
                # TLS terminates at the AWS Load Balancer Controller using ACM,
                # so no Kubernetes TLS Secret is created or placed in values.
                "tls": {"enabled": False, "secretName": ""},
                "gcpManagedTls": {
                    "enabled": False,
                    "certificateName": "platform-managed-cert",
                    "frontendConfigName": "platform-frontend-config",
                },
            },
        },
        "network": {
            "enabled": True,
            "ingressSourceCidrs": _cidr_output(terraform_outputs, "ingress_source_cidrs"),
            "providerApiCidrs": _cidr_output(terraform_outputs, "provider_api_cidrs"),
            "privateServiceCidrs": _cidr_output(terraform_outputs, "private_service_cidrs"),
            "kubernetesApiCidrs": _cidr_output(terraform_outputs, "kubernetes_api_cidrs"),
            "rangeClusterApiCidrs": [],
            "rangeClusterApiPort": 6444,
            "rangeAccessCidrs": [],
            "rangeAccessPorts": [22, 3389],
        },
        "identity": {"serviceAccountRoleArns": {key: roles[key] for key in sorted(_WORKLOAD_ROLE_KEYS)}},
        "runtimeEnv": runtime_env,
        "runtime": {
            # References only. entrypoint.sh hydrates values from Secrets Manager
            # in-process; raw values never enter Helm history, ConfigMaps, or argv.
            "secretReferences": {
                "app": config.secrets["django_secret_key"],
                "database": config.secrets["db_password"],
            }
        },
        "images": validated_images,
    }


def _read_images(
    path: str | Path,
    *,
    allowed_roots: tuple[Path, ...],
) -> dict[str, object]:
    """Read attested image identities from an approved protected-input root."""
    _resolved, raw = _read_json_mapping(
        path,
        label="attested image identity file",
        allowed_roots=allowed_roots,
    )
    return raw


def _terraform_outputs(root: Path, *, aws_profile: str | None) -> dict[str, object]:
    """Read and validate the current EKS Terraform output object."""
    result = run_cmd(
        ["terraform", f"-chdir={root}", "output", "-json"],
        capture=True,
        profile=aws_profile,
    )
    stdout = getattr(result, "stdout", "")
    try:
        outputs = json.loads(stdout)
    except (TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("EKS Terraform output was not valid JSON") from exc
    if not isinstance(outputs, dict):
        raise RuntimeError("EKS Terraform output must be a JSON object")
    return outputs


def _apply_eks_terraform(
    root: Path,
    *,
    backend_config: Path,
    terraform_inputs: Path,
    aws_profile: str | None,
    dry_run: bool,
) -> None:
    """Initialize the isolated root, create a saved plan, and apply that plan."""
    plan_name = "shifter-eks.tfplan"
    run_cmd(
        [
            "terraform",
            f"-chdir={root}",
            "init",
            _TERRAFORM_NONINTERACTIVE,
            "-reconfigure",
            f"-backend-config={backend_config}",
        ],
        dry_run=dry_run,
        profile=aws_profile,
    )
    run_cmd(
        [
            "terraform",
            f"-chdir={root}",
            "plan",
            _TERRAFORM_NONINTERACTIVE,
            f"-var-file={terraform_inputs}",
            f"-out={plan_name}",
        ],
        dry_run=dry_run,
        profile=aws_profile,
    )
    run_cmd(["terraform", f"-chdir={root}", "apply", plan_name], dry_run=dry_run, profile=aws_profile)


def deploy_eks(
    config_path: str | Path,
    images_path: str | Path,
    *,
    backend_config_path: str | Path | None = None,
    terraform_inputs_path: str | Path | None = None,
    aws_profile: str | None = None,
    dry_run: bool = False,
) -> dict[str, str]:
    """Apply a saved EKS plan and atomically roll out the shared Helm chart."""
    config = load_root_config(config_path)
    _validate_config(config)
    profile = config.deployment.profile
    # Select the EKS component so preflight validates the isolated EKS root's inputs, not the
    # legacy core/range/portal defaults (#1828).
    preflight_gate(Cloud.AWS, Mode.LOCAL, profile, component="eks", headless=True)
    root = eks_root(profile)
    allowed_roots = _protected_input_roots()
    backend_config = _required_file(
        backend_config_path,
        label="EKS Terraform backend config",
        allowed_roots=allowed_roots,
    )
    terraform_inputs = _validate_terraform_inputs(
        terraform_inputs_path,
        config,
        allowed_roots=allowed_roots,
    )
    _apply_eks_terraform(
        root,
        backend_config=backend_config,
        terraform_inputs=terraform_inputs,
        aws_profile=aws_profile,
        dry_run=dry_run,
    )
    health_url = f"https://{config.deployment.domain}/health/"
    if dry_run:
        return {"backend": "aws", "profile": profile, "health_url": health_url}

    outputs = _terraform_outputs(root, aws_profile=aws_profile)
    run_cmd(
        [
            "aws",
            "eks",
            "update-kubeconfig",
            "--name",
            str(_output(outputs, "cluster_name")),
            "--region",
            str(config.settings["region"]),
            "--role-arn",
            str(_output(outputs, "cluster_access_role_arn")),
            "--alias",
            f"shifter-{profile}",
        ],
        profile=aws_profile,
    )
    _wait_for_managed_addons(str(_output(outputs, "cluster_name")), aws_profile=aws_profile)
    _bootstrap_cluster(outputs, str(config.settings["region"]))
    values = render_aws_values(
        config,
        outputs,
        _read_images(images_path, allowed_roots=allowed_roots),
    )
    chart = get_repo_root() / "platform" / "charts" / "shifter"
    provider_values = chart / f"values-aws-{profile}.yaml"
    _run_helm_with_values(["helm", "lint", str(chart), "--values", str(provider_values)], values)
    _run_helm_with_values(
        [
            "helm",
            "template",
            _HELM_RELEASE,
            str(chart),
            "--values",
            str(provider_values),
        ],
        values,
    )
    _run_helm_with_values(
        [
            "helm",
            "upgrade",
            "--install",
            _HELM_RELEASE,
            str(chart),
            "--namespace",
            _EKS_NAMESPACE,
            "--create-namespace",
            "--values",
            str(provider_values),
            "--atomic",
            "--wait",
            "--timeout",
            "15m",
        ],
        values,
    )
    roles = _output(outputs, "workload_role_arns")
    if not isinstance(roles, Mapping):
        raise RuntimeError("workload_role_arns must be a mapping for effective IRSA readiness")
    _verify_kubernetes_security_enforcement(str(values["images"]["platform"]))
    _verify_effective_irsa(roles, str(values["images"]["platform"]))
    run_cmd(["curl", "--fail", "--silent", "--show-error", "--max-time", "30", health_url])
    return {"backend": "aws", "profile": profile, "health_url": health_url}


def teardown_eks(
    config_path: str | Path,
    *,
    backend_config_path: str | Path | None = None,
    terraform_inputs_path: str | Path | None = None,
    aws_profile: str | None = None,
    dry_run: bool = False,
) -> None:
    """Remove the Helm release and only the isolated EKS Terraform root."""
    config = load_root_config(config_path)
    _validate_config(config)
    root = eks_root(config.deployment.profile)
    allowed_roots = _protected_input_roots()
    backend_config = _required_file(
        backend_config_path,
        label="EKS Terraform backend config",
        allowed_roots=allowed_roots,
    )
    terraform_inputs = _validate_terraform_inputs(
        terraform_inputs_path,
        config,
        allowed_roots=allowed_roots,
    )
    run_cmd(["helm", "uninstall", _HELM_RELEASE, "--namespace", _EKS_NAMESPACE, "--wait"], dry_run=dry_run)
    run_cmd(
        [
            "terraform",
            f"-chdir={root}",
            "init",
            _TERRAFORM_NONINTERACTIVE,
            "-reconfigure",
            f"-backend-config={backend_config}",
        ],
        dry_run=dry_run,
        profile=aws_profile,
    )
    run_cmd(
        [
            "terraform",
            f"-chdir={root}",
            "destroy",
            "-auto-approve",
            f"-var-file={terraform_inputs}",
        ],
        dry_run=dry_run,
        profile=aws_profile,
    )
    if dry_run:
        return
    state = run_cmd(
        ["terraform", f"-chdir={root}", "state", "list"],
        capture=True,
        profile=aws_profile,
    )
    if getattr(state, "stdout", "").strip():
        raise RuntimeError("EKS teardown postcondition failed: isolated EKS state is not empty")
