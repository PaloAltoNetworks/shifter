"""Explicit AWS EKS lifecycle owner for the root-configured AWS bundle.

The platform control plane is Terraform-owned infrastructure plus the single
provider-neutral Helm chart. ECS remains a separate range-task transport and is
never read, imported, adopted, or destroyed by this module.
"""

from __future__ import annotations

import base64
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
    render_model_access_catalog,
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
# Dedicated pre-helm schema-migration + content-bootstrap Job (#1826). The SA and the
# platform-runtime ConfigMap are pre-created with the shifter release's Helm-ownership
# metadata so the chart adopts (not collides with) them; the Job is deleted after it
# completes. _PLATFORM_NAMESPACE matches the chart's namespaces.platform.
_PLATFORM_NAMESPACE = "shifter-platform"
_MIGRATOR_SERVICE_ACCOUNT = "migrator"
_MIGRATION_JOB = "platform-migrate"
_BATCH_V1_API_VERSION = "batch/v1"
_KUBECTL_WAIT_FOR_COMPLETE = "--for=condition=complete"
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
# Probed only when the environment defines the role (see _OPTIONAL_WORKLOAD_ROLE_KEYS).
_OPTIONAL_IRSA_PROBE_IDENTITIES = {
    "artifactAcquirer": ("shifter-acquisition", "artifact-acquirer"),
    "nodePoolLabeler": ("shifter-platform", "node-pool-labeler"),
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
_WORKLOAD_ROLE_KEYS = frozenset({"portal", "workers", "ctfScheduler", "provisionerLauncher", "provisioner", "migrator"})
# Workload roles an environment may define. Their presence enables the matching
# capability: artifactAcquirer turns on isolated feature-artifact acquisition
# Jobs (ADR-034-R12, #2463); nodePoolLabeler turns on the trusted runtime-plugin
# node-pool labeler (#2526).
_OPTIONAL_WORKLOAD_ROLE_KEYS = frozenset({"artifactAcquirer", "nodePoolLabeler"})
# Single source of truth in the installation package (installation.runtime_inventory_aws),
# so the renderer and the backend bundle's generated-output projection cannot drift.
_RENDERER_OWNED_RUNTIME_ENV = AWS_RENDERER_OWNED_RUNTIME_ENV_KEYS

# Guacamole data-plane identifiers (AWS EKS parity with the GCP cloud-sql/secrets
# modules). The dedicated database + password role are provisioned in-cluster by
# provision_guacamole_database; the guacamole-runtime k8s Secret carrying
# POSTGRESQL_USER/POSTGRESQL_PASSWORD/JSON_SECRET_KEY is synced before Helm runs.
_GUACAMOLE_DATABASE_NAME = "guacamole"
# ALB target health checks use each service's readiness-probe path (the chart's
# web and guacamole-client Deployments), so the load balancer and Kubernetes
# judge a pod by the same endpoint. The ALB default, "/", answers with a
# redirect or not-found and never matches 200.
_ALB_HEALTH_CHECK_PATHS = {"portal": "/health/", "guacamoleClient": "/guacamole/"}
_GUACAMOLE_RUNTIME_SECRET_NAME = "guacamole-runtime"  # noqa: S105 - Secret container name.  # nosec B105
_GUACAMOLE_DB_SECRET_NAME = "guacamole-db"  # noqa: S105 - Secret container name.  # nosec B105
_GUACAMOLE_JSON_AUTH_SECRET_NAME = "guacamole-json-auth"  # noqa: S105 - Secret container name.  # nosec B105
_GUACAMOLE_NAMESPACE = "shifter-platform"
_GUACAMOLE_PROVISION_JOB = "guacamole-db-provision"
_GUACAMOLE_PROVISION_SERVICE_ACCOUNT = "guacamole-db-provisioner"
_GUACAMOLE_PROVISION_IDENTITY = "guacamoleProvisioner"
_PART_OF_LABEL = "app.kubernetes.io/part-of"
# Deployed-pod default email backend (console: mail is logged, not sent). Mirrors
# the GCP renderer's empty-email fallback; keeps config._email from failing closed.
_CONSOLE_EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
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


def _validated_runtime_env(outputs: Mapping[str, object]) -> dict[str, str]:
    """Return validated Terraform-owned runtime variables.

    Values must be strings but MAY be empty: the Terraform contract emits empty
    strings for optional runtime keys that are off for this environment (e.g.
    DC_DOMAIN_NAME when no Windows DC scenario is deployed, and absent range
    exports that eks-provisioner-env defaults to ""). Only the required keys must
    be present and non-empty.
    """
    raw = _output(outputs, "runtime_env")
    if not isinstance(raw, Mapping) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in raw.items()
    ):
        raise ValueError("runtime_env must map string keys to string values")
    conflicting = sorted(_RENDERER_OWNED_RUNTIME_ENV.intersection(raw))
    if conflicting:
        raise ValueError("runtime_env must not override renderer-owned keys: " + ", ".join(conflicting))
    missing = sorted(AWS_EKS_REQUIRED_RUNTIME_ENV_KEYS.difference(raw))
    if missing:
        raise ValueError("runtime_env is missing required keys: " + ", ".join(missing))
    empty_required = sorted(key for key in AWS_EKS_REQUIRED_RUNTIME_ENV_KEYS if not raw[key])
    if empty_required:
        raise ValueError("required runtime_env keys must be non-empty: " + ", ".join(empty_required))
    return dict(raw)


def _rendered_env_values(rendered: str) -> dict[str, str]:
    """Parse newline-delimited key-value output from a trusted renderer."""
    values = {}
    for line in rendered.splitlines():
        key, value = line.split("=", 1)
        values[key] = value
    return values


def _aws_account_id(outputs: Mapping[str, object]) -> str:
    """Extract the account identifier from the cluster access role ARN."""
    access_role_arn = str(_output(outputs, "cluster_access_role_arn"))
    arn_parts = access_role_arn.split(":")
    if len(arn_parts) < 6 or arn_parts[0:3] != ["arn", "aws", "iam"] or not arn_parts[4]:
        raise ValueError("cluster_access_role_arn must be an AWS IAM ARN with an account id")
    return arn_parts[4]


def _runtime_env(config: RootConfig, outputs: Mapping[str, object]) -> dict[str, str]:
    """Build the complete canonical runtime environment for AWS EKS."""
    domain = config.deployment.domain
    return {
        **_validated_runtime_env(outputs),
        "AUDIT_DEPLOYMENT_SCOPE": (
            f"aws:{_aws_account_id(outputs)}:{config.settings['region']}:{config.deployment.profile}"
        ),
        "AUTH_PROVIDER": "oidc",
        "CLOUD_PROVIDER": "aws",
        "DJANGO_ALLOWED_HOSTS": f"{domain},localhost,127.0.0.1",
        "DJANGO_CSRF_TRUSTED_ORIGINS": f"https://{domain}",
        # Deployed pods run outside build/dev-default mode, so config._email requires
        # EMAIL_BACKEND explicitly. Default to the console backend (mail logged, never
        # silently dropped), mirroring the GCP renderer's empty-tfvar fallback; a
        # provider backend (e.g. django-ses) is a follow-up once SES is provisioned.
        "EMAIL_BACKEND": _CONSOLE_EMAIL_BACKEND,
        # The Django runtime mode (development/production); keyed by Django settings.
        "ENVIRONMENT": _runtime_environment(config.deployment.profile),
        # The AWS infrastructure environment name (dev/proof/prod) used by the
        # standalone provisioner to tag and scope range resources. It must equal the
        # Terraform/IAM environment (local.environment == the deployment profile), not
        # the Django ENVIRONMENT (development/production): the provisioner-iam tag
        # conditions and resource/secret ARNs are all keyed on this name, so tagging a
        # range resource with the Django value would be IAM-denied (#1826).
        "DEPLOYMENT_ENVIRONMENT": config.deployment.profile,
        # Schema migrations run once in the dedicated pre-helm migration Job
        # (_run_database_migrations), so every deployed pod skips them on startup.
        # Per-pod migrations made the launcher's startup exceed its liveness window
        # under DB load and crash-loop; the migration Job overrides this to "" (#1826).
        "SKIP_MIGRATIONS": "1",
        **_rendered_env_values(render_model_access_env(config)),
        **_rendered_env_values(render_mission_control_lease_env(config)),
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
    from installation.aws_model_broker import AwsModelBrokerSettings, validate_aws_broker_intent

    if AwsModelBrokerSettings.model_validate(payload.get("model_broker", {})) != validate_aws_broker_intent(config):
        raise ValueError("protected Terraform broker input differs from shifter.yaml")
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
                        _PART_OF_LABEL: "shifter",
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


def _install_load_balancer_controller(cluster_name: str, role_arn: str, vpc_id: str, region: str) -> None:
    """Install the AWS load-balancer controller bound to its exact IRSA role.

    vpcId and region are passed explicitly so the controller never queries IMDS:
    the node launch template pins http_put_response_hop_limit = 1, which blocks
    pod access to IMDS (a deliberate hardening that forces IRSA and stops a
    compromised pod from reading node-role credentials). Without these, the
    controller's IMDS-based VPC discovery times out and it CrashLoops. AWS auth is
    still via the IRSA role annotation below.
    """
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
            "--set-string",
            f"vpcId={vpc_id}",
            "--set-string",
            f"region={region}",
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
    # Restart the controller so the webhook pods serve the cert that matches the
    # caBundle Helm just wrote. The chart's genSignedCert regenerates the
    # aws-load-balancer-tls Secret and the webhook caBundle on every upgrade, but
    # already-running pods keep serving the previous cert from memory. That leaves a
    # window where webhook calls fail TLS ("x509: certificate signed by unknown
    # authority"), which breaks the very next chart install that creates Services or
    # an Ingress. A restart makes the serving cert and the caBundle consistent.
    run_cmd(
        [
            "kubectl",
            "rollout",
            "restart",
            "deployment/aws-load-balancer-controller",
            "--namespace",
            "kube-system",
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
    bundle = _output(outputs, "bundle_outputs")
    if not isinstance(bundle, Mapping) or not isinstance(bundle.get("vpc_id"), str):
        raise ValueError("bundle_outputs must include the cluster vpc_id")
    _apply_platform_namespaces()
    _install_load_balancer_controller(cluster_name, str(roles["ingress"]), str(bundle["vpc_id"]), region)
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
    identities = {
        **_IRSA_PROBE_IDENTITIES,
        **{name: target for name, target in _OPTIONAL_IRSA_PROBE_IDENTITIES.items() if name in roles},
    }
    if not all(isinstance(roles[name], str) for name in identities):
        raise ValueError("IRSA probe role ARNs must be strings")

    role_arns = {name: str(roles[name]) for name in identities}
    with tempfile.TemporaryDirectory(prefix="shifter-irsa-readiness-") as staging:
        staging_path = Path(staging)
        for identity, (namespace, service_account) in identities.items():
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
    """Build a restricted container that records denied API egress.

    The AWS VPC CNI network-policy agent programs a freshly-applied policy into
    eBPF asynchronously; in "standard" enforcing mode a newly-created pod has a
    brief allow window before its egress rules are installed (#1826). The probe
    therefore polls until the default-deny is enforced (steady state) rather than
    sampling once and racing the agent's programming latency (a single sample
    plus CrashLoopBackOff retries can miss the enforcement-transition window
    inside the rollout timeout). A policy that never blocks still fails closed:
    the loop raises after its deadline, so the deployment/job never succeeds.
    """
    marker_path = "/var/run/shifter-readiness/networkpolicy-ok"
    success_action = (
        f'Path("{marker_path}").touch()\ntime.sleep(300)' if workload == "deployment" else "raise SystemExit(0)"
    )
    script = f"""import socket, time
from pathlib import Path


def _api_blocked():
    try:
        connection = socket.create_connection(("kubernetes.default.svc", 443), timeout=5)
    except OSError:
        return True
    connection.close()
    return False


deadline = time.monotonic() + 240
while not _api_blocked():
    if time.monotonic() >= deadline:
        raise RuntimeError("default-deny NetworkPolicy allowed Kubernetes API access")
    time.sleep(3)
print("NETWORK_POLICY_OK:{workload}", flush=True)
{success_action}
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
        "apiVersion": _BATCH_V1_API_VERSION,
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
                    _KUBECTL_WAIT_FOR_COMPLETE,
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


def _bundle_outputs(terraform_outputs: Mapping[str, object]) -> Mapping[str, object]:
    """Return the validated bundle_outputs mapping from the eks Terraform outputs."""
    bundle = _output(terraform_outputs, "bundle_outputs")
    if not isinstance(bundle, Mapping):
        raise ValueError("bundle_outputs must be a mapping")
    return bundle


def _bundle_secret_arns(terraform_outputs: Mapping[str, object]) -> Mapping[str, object]:
    """Return the validated bundle_outputs.secret_arns mapping (name -> ARN)."""
    secret_arns = _bundle_outputs(terraform_outputs).get("secret_arns")
    if not isinstance(secret_arns, Mapping):
        raise ValueError("bundle_outputs.secret_arns must map eks workload secret names to ARNs")
    return secret_arns


def _workload_secret_arns(terraform_outputs: Mapping[str, object]) -> dict[str, str]:
    """Return the eks-owned workload secret ARNs (role-readable) keyed by name.

    The portal role can read only shifter/<env>/eks/* (kms_secrets.tf + iam.tf), so
    the portal/worker secret references and _populate_eks_workload_secrets both key
    off these ARNs from the eks module's secret_arns output.
    """
    secret_arns = _bundle_secret_arns(terraform_outputs)
    resolved: dict[str, str] = {}
    # guacamole-json-auth is the shared JSON-auth signing key the portal entrypoint
    # hydrates into GUACAMOLE_JSON_AUTH_SECRET; it is role-readable like the rest.
    for name in ("database", "django", "cognito", "guacamole-json-auth"):
        arn = secret_arns.get(name)
        if not isinstance(arn, str) or not arn:
            raise ValueError(f"bundle_outputs.secret_arns is missing the '{name}' workload secret ARN")
        resolved[name] = arn
    return resolved


def _guacamole_db_endpoint(terraform_outputs: Mapping[str, object]) -> tuple[str, str]:
    """Return the (host, port) of the shared portal RDS for guacamole PostgreSQL."""
    bundle = _bundle_outputs(terraform_outputs)
    host = bundle.get("portal_db_address")
    if not isinstance(host, str) or not host:
        raise ValueError("bundle_outputs.portal_db_address is required for the guacamole PostgreSQL host")
    port = bundle.get("portal_db_port")
    if not isinstance(port, (str, int)) or not str(port):
        raise ValueError("bundle_outputs.portal_db_port is required for the guacamole PostgreSQL port")
    return host, str(port)


def _validated_workload_roles(terraform_outputs: Mapping[str, object]) -> Mapping[str, str]:
    """The workload IRSA role map, required to cover every chart workload identity."""
    roles = _output(terraform_outputs, "workload_role_arns")
    if not isinstance(roles, Mapping) or not all(isinstance(k, str) and isinstance(v, str) for k, v in roles.items()):
        raise ValueError("workload_role_arns must map exact service-account names to IAM role ARNs")
    missing_roles = sorted(_WORKLOAD_ROLE_KEYS.difference(roles))
    if missing_roles:
        raise ValueError("workload_role_arns is missing chart workload roles: " + ", ".join(missing_roles))
    return roles


def _feature_artifact_job_image(roles: Mapping[str, str], validated_images: Mapping[str, str]) -> str:
    """The image isolated feature-artifact acquisition Jobs run (#2463), or "" when disabled.

    Acquisition is enabled only where the environment defines the
    artifactAcquirer identity; an empty image keeps the launcher's acquisition
    reconcile a no-op elsewhere. The Jobs run the platform image.
    """
    if "artifactAcquirer" not in roles:
        return ""
    if "platform" not in validated_images:
        raise ValueError("images must include the digest-pinned 'platform' identity for feature-artifact acquisition")
    return validated_images["platform"]


def _runtime_plugin_pool_values(roles: Mapping[str, str], terraform_outputs: Mapping[str, object]) -> dict[str, object]:
    """The trusted runtime-plugin node-pool labeler (#2526), enabled with the plugin pool.

    The labeler identity and the pool's Auto Scaling group come from the same
    Terraform toggle, so exactly one of them present means a misconfigured
    environment.
    """
    raw = terraform_outputs.get("runtime_plugin_node_group_asg")
    node_group_asg = raw.get("value", "") if isinstance(raw, Mapping) else ""
    if not isinstance(node_group_asg, str):
        raise ValueError("runtime_plugin_node_group_asg must be a string")
    labeler = "nodePoolLabeler" in roles
    if labeler != bool(node_group_asg):
        raise ValueError("the runtime-plugin pool and the nodePoolLabeler identity must be enabled together")
    if node_group_asg and not re.fullmatch(r"[\w+=,.@/:-]{1,255}", node_group_asg):
        raise ValueError("runtime_plugin_node_group_asg must be an Auto Scaling group name")
    return {"labeler": {"enabled": labeler, "nodeGroupAsg": node_group_asg}}


def _edge_values(config: RootConfig, terraform_outputs: Mapping[str, object]) -> dict[str, object]:
    """Public edge: ALB ingress with ACM TLS and WAF, restricted to the edge client CIDRs."""
    edge_client_cidrs = _cidr_output(terraform_outputs, "edge_client_cidrs")
    return {
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
    }


def _aws_feature_artifact_acquisition_values(terraform_outputs: Mapping[str, object]) -> dict[str, object]:
    """Acquisition Job egress: the provider-API HTTPS egress minus the service CIDR.

    The Job's identity rides the IRSA role annotation the chart sets from
    identity.serviceAccountRoleArns, so no extra service-account annotations.
    """
    return {
        "serviceAccountAnnotations": {},
        "egressCidrs": _cidr_output(terraform_outputs, "provider_api_cidrs"),
        "egressExcept": _cidr_output(terraform_outputs, "provider_api_egress_except"),
    }


def render_aws_values(
    config: RootConfig,
    terraform_outputs: Mapping[str, object],
    images: Mapping[str, object],
) -> dict[str, object]:
    """Render non-secret AWS values from validated config, outputs, and digests."""
    _validate_config(config)
    roles = _validated_workload_roles(terraform_outputs)
    validated_images = _validated_images(images)
    if "provisioner" not in validated_images:
        raise ValueError("images must include a digest-pinned 'provisioner' identity for the Kubernetes Job launcher")
    # The portal/worker entrypoints hydrate the DB, app and OIDC secrets using the
    # portal workload IRSA role, which can read only the eks-owned shifter/<env>/eks/*
    # secrets. Reference those ARNs so the role can read them; _populate_eks_workload_secrets
    # fills them from the portal's canonical credential secrets before Helm runs.
    secret_arns = _workload_secret_arns(terraform_outputs)
    # ENGINE_TASK_IMAGE is the provisioner Job image; the launcher resolves it
    # from the runtime env. It is renderer-generated from the attested digest,
    # mirroring GCP's render_runtime_env.py.
    runtime_env = _runtime_env(config, terraform_outputs)
    runtime_env["ENGINE_TASK_IMAGE"] = validated_images["provisioner"]
    runtime_env["FEATURE_ARTIFACT_JOB_IMAGE"] = _feature_artifact_job_image(roles, validated_images)
    # Provisioner-Job admission contract (restrict-provisioner-jobs, #1826). The
    # launcher builds the Job with imagePullPolicy = ENGINE_TASK_IMAGE_PULL_POLICY
    # (GCPTaskRunner default IfNotPresent) and DB_USER = provisioner_lambda
    # (eks-provisioner-env), and the policy pins the Job to these exact values.
    # They must be present so the policy admits the real Job.
    runtime_env["ENGINE_TASK_IMAGE_PULL_POLICY"] = "IfNotPresent"
    runtime_env["PROVISIONER_DB_USER"] = "provisioner_lambda"
    # OIDC is hydrated by the portal/workers, whose role can read only the
    # eks-owned shifter/<env>/eks/* secrets. Terraform's OIDC_SECRET_ID points at
    # the portal-owned cognito secret the role cannot read, so repoint it at the
    # eks-owned copy that _populate_eks_workload_secrets fills. Not forwarded to the
    # provisioner Job (it uses RDS IAM auth), so this is portal/worker-scoped.
    runtime_env["OIDC_SECRET_ID"] = secret_arns["cognito"]
    # Guacamole: the portal signs JSON-auth tokens and guacamole-client validates
    # them with the shared key, so the portal entrypoint hydrates
    # GUACAMOLE_JSON_AUTH_SECRET from this eks-owned secret. The PostgreSQL host is
    # the shared portal RDS; the dedicated guacamole database + guacamole_admin role
    # are provisioned in-cluster (provision_guacamole_database) before Helm runs.
    guacamole_db_host, guacamole_db_port = _guacamole_db_endpoint(terraform_outputs)
    runtime_env["GUACAMOLE_SECRET_ID"] = secret_arns["guacamole-json-auth"]
    runtime_env["GUACAMOLE_POSTGRESQL_HOSTNAME"] = guacamole_db_host
    runtime_env["GUACAMOLE_POSTGRESQL_PORT"] = guacamole_db_port
    runtime_env["GUACAMOLE_POSTGRESQL_DATABASE"] = _GUACAMOLE_DATABASE_NAME
    from installation.aws_model_broker import project_aws_model_broker

    broker = project_aws_model_broker(
        terraform_outputs.get("model_broker", {}).get("value"),
        config=config,
        catalog_json=render_model_access_catalog(config),
        model_access_env=render_model_access_env(config),
        account_id=_aws_account_id(terraform_outputs),
    )
    if broker["enabled"] and broker["provisioner_subject"] != roles["provisioner"]:
        raise ValueError("broker enrollment identity differs from the provisioner workload")
    runtime_env.update(
        {
            "MODEL_BROKER_GUEST_URL": "",
            "MODEL_BROKER_GUEST_CIDRS": "",
            "MODEL_ENROLLMENT_CONTROL_URL": "",
            "MODEL_ENROLLMENT_CA_PEM_B64": "",
            **broker.get("enrollment_env", {}),
        }
    )
    return {
        "provider": {"name": "aws"},
        "modelBroker": broker,
        "deployment": {"name": config.deployment.name, "profile": config.deployment.profile},
        "capabilities": {
            "kubernetesJobLauncher": True,
            "featureArtifactAcquisition": bool(runtime_env["FEATURE_ARTIFACT_JOB_IMAGE"]),
        },
        "provisioner": {"taskRunner": "aws"},
        "edge": _edge_values(config, terraform_outputs),
        "featureArtifactAcquisition": _aws_feature_artifact_acquisition_values(terraform_outputs),
        "runtimePluginPool": _runtime_plugin_pool_values(roles, terraform_outputs),
        "services": {
            service: {"annotations": {"alb.ingress.kubernetes.io/healthcheck-path": path}}
            for service, path in _ALB_HEALTH_CHECK_PATHS.items()
        },
        "network": {
            "enabled": True,
            "ingressSourceCidrs": _cidr_output(terraform_outputs, "ingress_source_cidrs"),
            "providerApiCidrs": sorted(
                set(_cidr_output(terraform_outputs, "provider_api_cidrs") + broker.get("endpoint_cidrs", []))
            ),
            # Carve the cluster service CIDR out of the wildcard provider-API (443)
            # egress so the broad AWS-API allow cannot also reach the in-cluster
            # Kubernetes API (kubernetes.default ClusterIP). Only the launcher
            # policy then grants API access (#1826).
            "providerApiEgressExcept": _cidr_output(terraform_outputs, "provider_api_egress_except"),
            "privateServiceCidrs": _cidr_output(terraform_outputs, "private_service_cidrs"),
            "kubernetesApiCidrs": _cidr_output(terraform_outputs, "kubernetes_api_cidrs"),
            "rangeClusterApiCidrs": [],
            "rangeClusterApiPort": 6444,
            # The RAES provisioner Job SSHes into range guests to bootstrap them.
            # Guests are private-only on the peered range network, so without this
            # the jobs default-deny drops the provisioner -> guest path and every
            # SSH wait times out even though the guest is up (#1826). Source the
            # CIDR from the same RANGE_VPC_CIDR the provisioner targets so the
            # policy and the realized addressing can never diverge; an unset value
            # leaves the chart's `if .rangeAccessCidrs` guard false (fail closed).
            "rangeAccessCidrs": [runtime_env["RANGE_VPC_CIDR"]] if runtime_env.get("RANGE_VPC_CIDR") else [],
            "rangeAccessPorts": [22, 3389],
        },
        "identity": {
            "serviceAccountRoleArns": {
                key: roles[key] for key in sorted(_WORKLOAD_ROLE_KEYS | (_OPTIONAL_WORKLOAD_ROLE_KEYS & set(roles)))
            }
        },
        "guacamoleRuntimeSecret": {"name": _GUACAMOLE_RUNTIME_SECRET_NAME},
        "runtimeEnv": runtime_env,
        "runtime": {
            # References only. entrypoint.sh hydrates values from Secrets Manager
            # in-process; raw values never enter Helm history, ConfigMaps, or argv.
            "secretReferences": {
                "app": secret_arns["django"],
                "database": secret_arns["database"],
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


_EKS_WORKLOAD_SECRET_SOURCES: dict[str, str] = {
    # eks workload secret name (shifter/<env>/eks/<name>) -> portal-owned source.
    # DB creds ({host,port,dbname,username,password,engine}) come from the RDS
    # module's credential secret; the app bundle ({django_secret_key,
    # field_encryption_key}) from the portal app secret. Both are env-suffixed.
    "database": "shifter-{environment}-portal-db-credentials",
    "django": "shifter-{environment}-portal-app",
    # OIDC client bundle ({client_id,client_secret,issuer_url,domain,user_pool_id}).
    "cognito": "shifter-{environment}-portal-cognito",
}


def _populate_eks_workload_secrets(
    outputs: Mapping[str, object],
    *,
    environment: str,
    region: str,
    aws_profile: str | None,
) -> None:
    """Fill the empty eks-owned workload secrets from the portal's canonical ones.

    modules/portal/eks/kms_secrets.tf creates shifter/<env>/eks/{database,django,...}
    as empty containers that only the portal IRSA role may read; the real values
    live in the portal RDS/app secrets. Copy them in before Helm so the portal and
    worker entrypoints can hydrate DB_SECRET_ID/APP_SECRET_ID. Each value moves
    through a 0600 temp file (put-secret-value --secret-string file://...) so it
    never lands on argv or in the operator log (run_cmd logs only the command).
    """
    secret_arns = _workload_secret_arns(outputs)
    for name, source_template in _EKS_WORKLOAD_SECRET_SOURCES.items():
        target_arn = secret_arns[name]
        source = source_template.format(environment=environment)
        fetched = run_cmd(
            [
                "aws",
                "secretsmanager",
                "get-secret-value",
                "--secret-id",
                source,
                "--region",
                region,
                "--query",
                "SecretString",
                "--output",
                "text",
            ],
            capture=True,
            profile=aws_profile,
        )
        payload = str(fetched.stdout).rstrip("\n")
        handle, path = tempfile.mkstemp(suffix=f"-{name}.json")
        os.close(handle)
        try:
            secret_file = Path(path)
            secret_file.chmod(0o600)
            secret_file.write_text(payload, encoding="utf-8")
            run_cmd(
                [
                    "aws",
                    "secretsmanager",
                    "put-secret-value",
                    "--secret-id",
                    target_arn,
                    "--region",
                    region,
                    "--secret-string",
                    f"file://{path}",
                ],
                profile=aws_profile,
            )
        finally:
            Path(path).unlink(missing_ok=True)


def _read_secret_string(secret_id: str, *, region: str, aws_profile: str | None) -> str:
    """Return a Secrets Manager SecretString without exposing it on argv."""
    fetched = run_cmd(
        [
            "aws",
            "secretsmanager",
            "get-secret-value",
            "--secret-id",
            secret_id,
            "--region",
            region,
            "--query",
            "SecretString",
            "--output",
            "text",
        ],
        capture=True,
        profile=aws_profile,
    )
    return str(fetched.stdout).rstrip("\n")


def _guacamole_secret_arns(outputs: Mapping[str, object]) -> tuple[str, str]:
    """Return (guacamole-db ARN, guacamole-json-auth ARN) from bundle_outputs."""
    secret_arns = _bundle_secret_arns(outputs)
    db_arn = secret_arns.get(_GUACAMOLE_DB_SECRET_NAME)
    json_arn = secret_arns.get(_GUACAMOLE_JSON_AUTH_SECRET_NAME)
    if not isinstance(db_arn, str) or not db_arn or not isinstance(json_arn, str) or not json_arn:
        raise ValueError("bundle_outputs.secret_arns is missing the guacamole secret ARNs")
    return db_arn, json_arn


def _sync_guacamole_runtime_secret(
    outputs: Mapping[str, object],
    *,
    region: str,
    aws_profile: str | None,
) -> None:
    """Create the guacamole-runtime Kubernetes Secret from the eks-owned guacamole secrets.

    guacamole-client reads POSTGRESQL_USER/POSTGRESQL_PASSWORD/JSON_SECRET_KEY from
    this Secret via envFrom; the values are the Terraform-generated guacamole_admin
    credentials and the shared JSON-auth signing key (also hydrated by the portal as
    GUACAMOLE_JSON_AUTH_SECRET). Mirrors GCP's sync_gcp_guacamole_runtime_secret; the
    manifest is streamed to kubectl over stdin so values never reach disk, argv or the log.
    """
    db_arn, json_arn = _guacamole_secret_arns(outputs)
    db_payload = json.loads(_read_secret_string(db_arn, region=region, aws_profile=aws_profile))
    json_auth = _read_secret_string(json_arn, region=region, aws_profile=aws_profile)
    manifest = {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {
            "name": _GUACAMOLE_RUNTIME_SECRET_NAME,
            "namespace": _GUACAMOLE_NAMESPACE,
            "labels": {_PART_OF_LABEL: "shifter"},
        },
        "type": "Opaque",
        "stringData": {
            "POSTGRESQL_USER": db_payload["username"],
            "POSTGRESQL_PASSWORD": db_payload["password"],
            "JSON_SECRET_KEY": json_auth,
        },
    }
    return_code = run_cmd_secret_stdin(
        ["kubectl", "apply", "-f", "-"],
        secret_stdin=json.dumps(manifest),
    )
    if return_code != 0:
        raise RuntimeError("failed to apply the guacamole runtime Secret")


def _guacamole_provision_secret_arns(outputs: Mapping[str, object]) -> dict[str, str]:
    """Return the master-DB + guacamole-db ARNs the provisioner command reads."""
    secret_arns = _bundle_secret_arns(outputs)
    resolved: dict[str, str] = {}
    for name in ("database", _GUACAMOLE_DB_SECRET_NAME):
        arn = secret_arns.get(name)
        if not isinstance(arn, str) or not arn:
            raise ValueError(f"bundle_outputs.secret_arns is missing '{name}' for guacamole provisioning")
        resolved[name] = arn
    return resolved


def _guacamole_provision_role_arn(outputs: Mapping[str, object]) -> str:
    """Return the exact-subject guacamoleProvisioner IRSA role ARN."""
    roles = _output(outputs, "workload_role_arns")
    role_arn = roles.get(_GUACAMOLE_PROVISION_IDENTITY) if isinstance(roles, Mapping) else None
    if not isinstance(role_arn, str) or not role_arn:
        raise ValueError("workload_role_arns must include the guacamoleProvisioner role")
    return role_arn


def _guacamole_provision_job_env(secret_arns: Mapping[str, str], region: str) -> list[dict[str, str]]:
    """Env for the provisioner command (it bypasses the portal entrypoint).

    The command only needs Django to initialise, not the full platform runtime env.
    ENVIRONMENT=build loads settings in tooling mode exactly as the image build's
    collectstatic does; the build-time placeholders below satisfy the settings that
    have no build default (DJANGO_SECRET_KEY, FIELD_ENCRYPTION_KEY, OIDC_*) and are
    never used by the command, which reads its DB credentials from Secrets Manager
    via IRSA and talks to RDS directly. The two keys are ephemeral (generated per
    run) and are not real credentials.
    """
    ephemeral_secret_key = base64.urlsafe_b64encode(os.urandom(32)).decode()
    ephemeral_fernet_key = base64.urlsafe_b64encode(os.urandom(32)).decode()
    return [
        {"name": "ENVIRONMENT", "value": "build"},
        {"name": "CLOUD_PROVIDER", "value": "aws"},
        {"name": "AWS_REGION", "value": region},
        {"name": "DJANGO_SECRET_KEY", "value": ephemeral_secret_key},
        {"name": "FIELD_ENCRYPTION_KEY", "value": ephemeral_fernet_key},
        {"name": "OIDC_RP_CLIENT_ID", "value": "build-time-client"},
        {"name": "OIDC_AUTH_DOMAIN", "value": "https://auth.example.test"},
        {"name": "OIDC_ISSUER_URL", "value": "https://issuer.example.test"},
        {"name": "DB_SECRET_ID", "value": secret_arns["database"]},
        {"name": "GUACAMOLE_DB_SECRET_ID", "value": secret_arns[_GUACAMOLE_DB_SECRET_NAME]},
    ]


def _guacamole_provision_manifests(
    *,
    role_arn: str,
    secret_arns: Mapping[str, str],
    region: str,
    platform_image: str,
) -> tuple[dict[str, object], dict[str, object]]:
    """Build the (ServiceAccount, Job) manifests for the guacamole DB provisioner."""
    labels = {_PART_OF_LABEL: "shifter"}
    service_account = {
        "apiVersion": "v1",
        "kind": "ServiceAccount",
        "metadata": {
            "name": _GUACAMOLE_PROVISION_SERVICE_ACCOUNT,
            "namespace": _GUACAMOLE_NAMESPACE,
            "labels": labels,
            "annotations": {"eks.amazonaws.com/role-arn": role_arn},
        },
    }
    job = {
        "apiVersion": _BATCH_V1_API_VERSION,
        "kind": "Job",
        "metadata": {"name": _GUACAMOLE_PROVISION_JOB, "namespace": _GUACAMOLE_NAMESPACE, "labels": labels},
        "spec": {
            "backoffLimit": 2,
            "template": {
                "metadata": {"labels": labels},
                "spec": {
                    "serviceAccountName": _GUACAMOLE_PROVISION_SERVICE_ACCOUNT,
                    "restartPolicy": "Never",
                    # Restricted-PSS-compliant (mirrors the IRSA readiness probe).
                    # readOnlyRootFilesystem is intentionally left unset so the portal
                    # entrypoint + Django have a writable scratch/overlay; the pod is
                    # one-shot and non-serving.
                    "securityContext": {
                        "runAsNonRoot": True,
                        "runAsUser": 1000,
                        "runAsGroup": 1000,
                        "seccompProfile": {"type": "RuntimeDefault"},
                    },
                    "containers": [
                        {
                            "name": "provision",
                            "image": platform_image,
                            "imagePullPolicy": "IfNotPresent",
                            # Override the portal entrypoint: run the command directly so
                            # it does not require the full platform runtime env.
                            "command": ["python", "manage.py", "provision_guacamole_database"],
                            "securityContext": {
                                "allowPrivilegeEscalation": False,
                                "capabilities": {"drop": ["ALL"]},
                            },
                            "env": _guacamole_provision_job_env(secret_arns, region),
                        }
                    ],
                },
            },
        },
    }
    return service_account, job


def _delete_guacamole_provision_job() -> None:
    """Delete the guacamole provisioner Job (idempotent; ignores absence)."""
    run_cmd(
        [
            "kubectl",
            "delete",
            "job",
            _GUACAMOLE_PROVISION_JOB,
            "--namespace",
            _GUACAMOLE_NAMESPACE,
            "--ignore-not-found",
        ]
    )


def _provision_guacamole_database(
    outputs: Mapping[str, object],
    *,
    region: str,
    platform_image: str,
) -> None:
    """Run the one-shot guacamole database/role provisioner Job before the chart install.

    RDS exposes no native Terraform user/database resource and the deploy runner has
    no network path to RDS, so the guacamole_admin password role and guacamole
    database are created from inside the cluster. The Job runs the portal image under
    the exact-subject guacamoleProvisioner IRSA role and runs
    manage.py provision_guacamole_database (idempotent), which reads the master +
    guacamole credentials from Secrets Manager and provisions RDS directly. It must
    complete before guacamole-client, whose entrypoint connects as guacamole_admin and
    initialises its schema.
    """
    service_account, job = _guacamole_provision_manifests(
        role_arn=_guacamole_provision_role_arn(outputs),
        secret_arns=_guacamole_provision_secret_arns(outputs),
        region=region,
        platform_image=platform_image,
    )
    # A completed Job's pod template is immutable, so clear any prior run first.
    _delete_guacamole_provision_job()
    for manifest in (service_account, job):
        handle, path = tempfile.mkstemp(suffix="-guacamole-provision.json")
        os.close(handle)
        try:
            Path(path).write_text(json.dumps(manifest), encoding="utf-8")
            run_cmd(["kubectl", "apply", "-f", str(path)])
        finally:
            Path(path).unlink(missing_ok=True)

    waited = run_cmd(
        [
            "kubectl",
            "wait",
            _KUBECTL_WAIT_FOR_COMPLETE,
            f"job/{_GUACAMOLE_PROVISION_JOB}",
            "--namespace",
            _GUACAMOLE_NAMESPACE,
            "--timeout=300s",
        ],
        check=False,
    )
    if waited is None or waited.returncode != 0:
        # Surface the pod logs (the command redacts secrets) before failing.
        run_cmd(
            ["kubectl", "logs", f"job/{_GUACAMOLE_PROVISION_JOB}", "--namespace", _GUACAMOLE_NAMESPACE, "--tail", "80"],
            check=False,
        )
        raise RuntimeError("guacamole database provisioning Job did not complete successfully")
    _delete_guacamole_provision_job()


def _write_private_api_kubeconfig(
    outputs: Mapping[str, object],
    *,
    alias: str,
    region: str,
    aws_profile: str | None,
) -> Path:
    """Point kubectl/helm at the private EKS API by control-plane ENI IP.

    The cluster endpoint is private-only (endpoint_public_access = false) and its
    Route 53 hosted zone is service-owned, so it cannot be associated with the
    self-hosted runner VPC and the runner cannot resolve the endpoint hostname
    (see modules/portal/eks/runner_network.tf). ``aws eks update-kubeconfig`` would
    write that unresolvable hostname. Instead connect by the control-plane ENI IP,
    reached over the runner<->EKS peering, with ``tls-server-name`` set to the
    endpoint host so the presented server certificate still validates. The ENIs
    are resolved fresh on every deploy, so control-plane ENI churn is picked up
    automatically. Auth uses ``aws eks get-token`` as the deploy role directly:
    that role holds the cluster's AmazonEKSClusterAdminPolicy access entry
    (aws_eks_access_entry.deployment), so no ``--role-arn`` is passed. Passing the
    deployment role there would make the deploy role assume itself, which fails
    with AssumeRole AccessDenied.
    """
    cluster_name = str(_output(outputs, "cluster_name"))
    ca_data = str(_output(outputs, "cluster_ca_certificate"))

    described = run_cmd(
        [
            "aws",
            "eks",
            "describe-cluster",
            "--name",
            cluster_name,
            "--region",
            region,
            "--query",
            "cluster.endpoint",
            "--output",
            "text",
        ],
        capture=True,
        profile=aws_profile,
    )
    endpoint_host = str(described.stdout).strip().removeprefix("https://").split("/")[0]

    enis = run_cmd(
        [
            "aws",
            "ec2",
            "describe-network-interfaces",
            "--region",
            region,
            "--filters",
            f"Name=description,Values=Amazon EKS {cluster_name}",
            "Name=status,Values=in-use",
            "--query",
            "NetworkInterfaces[].PrivateIpAddress",
            "--output",
            "text",
        ],
        capture=True,
        profile=aws_profile,
    )
    control_plane_ips = str(enis.stdout).split()
    if not control_plane_ips:
        raise SystemExit("No in-use EKS control-plane ENIs found; cannot reach the private API by IP.")

    kubeconfig = {
        "apiVersion": "v1",
        "kind": "Config",
        "clusters": [
            {
                "name": cluster_name,
                "cluster": {
                    "server": f"https://{control_plane_ips[0]}:443",
                    "tls-server-name": endpoint_host,
                    "certificate-authority-data": ca_data,
                },
            }
        ],
        "contexts": [{"name": alias, "context": {"cluster": cluster_name, "user": cluster_name}}],
        "current-context": alias,
        "users": [
            {
                "name": cluster_name,
                "user": {
                    "exec": {
                        "apiVersion": "client.authentication.k8s.io/v1beta1",
                        "command": "aws",
                        "args": [
                            "--region",
                            region,
                            "eks",
                            "get-token",
                            "--cluster-name",
                            cluster_name,
                            "--output",
                            "json",
                        ],
                    }
                },
            }
        ],
    }

    path = Path(tempfile.gettempdir()) / f"{alias}.kubeconfig"
    # kubeconfig is JSON, which kubectl/helm read as YAML; avoids a YAML dependency.
    path.write_text(json.dumps(kubeconfig), encoding="utf-8")
    path.chmod(0o600)
    os.environ["KUBECONFIG"] = str(path)
    return path


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
    _write_private_api_kubeconfig(
        outputs,
        alias=f"shifter-{profile}",
        region=str(config.settings["region"]),
        aws_profile=aws_profile,
    )
    _wait_for_managed_addons(str(_output(outputs, "cluster_name")), aws_profile=aws_profile)
    _populate_eks_workload_secrets(
        outputs,
        environment=profile,
        region=str(config.settings["region"]),
        aws_profile=aws_profile,
    )
    _bootstrap_cluster(outputs, str(config.settings["region"]))
    images = _read_images(images_path, allowed_roots=allowed_roots)
    # Guacamole (AWS EKS parity with GCP): create the guacamole-runtime Secret and
    # provision the guacamole database + guacamole_admin role in-cluster before Helm,
    # so guacamole-client can start and initialise its schema during --wait.
    _sync_guacamole_runtime_secret(
        outputs,
        region=str(config.settings["region"]),
        aws_profile=aws_profile,
    )
    _provision_guacamole_database(
        outputs,
        region=str(config.settings["region"]),
        platform_image=str(_validated_images(images)["platform"]),
    )
    values = render_aws_values(
        config,
        outputs,
        images,
    )
    # Migrate the schema and converge the in-box catalog / RAES image registry once,
    # before the chart install. Deployed pods then skip per-pod startup migrations
    # (SKIP_MIGRATIONS=1), which previously crash-looped the provisioner-launcher
    # under DB load (#1826). Pre-creates the Helm-adopted migrator SA + runtime
    # ConfigMap the chart owns afterward.
    _run_database_migrations(values)
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


def _migration_prerequisites(
    *,
    migrator_role_arn: str,
    runtime_env: Mapping[str, str],
    secret_refs: Mapping[str, str],
) -> dict[str, object]:
    """Build the Helm-adopted migrator ServiceAccount and platform-runtime ConfigMap.

    The migration Job runs before the chart install, so its IRSA ServiceAccount and the
    runtime ConfigMap it reads must already exist. Both carry the shifter release's Helm
    ownership metadata so the subsequent ``helm upgrade --install`` adopts them rather
    than failing on pre-existing resources (mirrors the GCP control-plane). The
    ConfigMap data replicates configmap-runtime.yaml (the rendered runtime env plus the
    ``APP_SECRET_ID``/``DB_SECRET_ID`` secret references) so the Job's entrypoint
    hydrates exactly the secrets the deployed pods do.
    """
    helm_labels = {_PART_OF_LABEL: "shifter", "app.kubernetes.io/managed-by": "Helm"}
    helm_annotations = {
        "meta.helm.sh/release-name": _HELM_RELEASE,
        "meta.helm.sh/release-namespace": _EKS_NAMESPACE,
    }
    configmap_data = dict(runtime_env)
    if secret_refs.get("app"):
        configmap_data["APP_SECRET_ID"] = secret_refs["app"]
    if secret_refs.get("database"):
        configmap_data["DB_SECRET_ID"] = secret_refs["database"]
    return {
        "apiVersion": "v1",
        "kind": "List",
        "items": [
            {
                "apiVersion": "v1",
                "kind": "ServiceAccount",
                "metadata": {
                    "name": _MIGRATOR_SERVICE_ACCOUNT,
                    "namespace": _PLATFORM_NAMESPACE,
                    "labels": {**helm_labels, "app.kubernetes.io/component": "migrator"},
                    "annotations": {**helm_annotations, "eks.amazonaws.com/role-arn": migrator_role_arn},
                },
            },
            {
                "apiVersion": "v1",
                "kind": "ConfigMap",
                "metadata": {
                    "name": "platform-runtime",
                    "namespace": _PLATFORM_NAMESPACE,
                    "labels": helm_labels,
                    "annotations": helm_annotations,
                },
                "data": configmap_data,
            },
        ],
    }


def _migration_job(platform_image: str) -> dict[str, object]:
    """Build the one-shot schema-migration + content-bootstrap Job.

    Runs through the portal entrypoint with ``SKIP_MIGRATIONS=""`` (overriding the
    runtime ConfigMap's ``"1"``) so it hydrates the runtime secrets, applies migrations
    as the RDS master, switches to portal_runtime RDS IAM auth, then registers the
    in-box catalog and seeds the RAES image registry. Deployed pods keep
    ``SKIP_MIGRATIONS=1`` and skip startup migrations, so this is the single migrator
    (#1826). Both management commands are idempotent, so a redeploy is a no-op.
    """
    labels = {_PART_OF_LABEL: "shifter", "app.kubernetes.io/component": "migrator"}
    return {
        "apiVersion": _BATCH_V1_API_VERSION,
        "kind": "Job",
        "metadata": {"name": _MIGRATION_JOB, "namespace": _PLATFORM_NAMESPACE, "labels": labels},
        "spec": {
            "backoffLimit": 0,
            "activeDeadlineSeconds": 900,
            "template": {
                "metadata": {"labels": labels},
                "spec": {
                    "serviceAccountName": _MIGRATOR_SERVICE_ACCOUNT,
                    "restartPolicy": "Never",
                    # Restricted-PSS-compliant; readOnlyRootFilesystem is left unset so
                    # the entrypoint + Django have writable scratch (mirrors the
                    # guacamole provisioner Job). The pod is one-shot and non-serving.
                    "securityContext": {
                        "runAsNonRoot": True,
                        "runAsUser": 1000,
                        "runAsGroup": 1000,
                        "seccompProfile": {"type": "RuntimeDefault"},
                    },
                    "containers": [
                        {
                            "name": "migrate",
                            "image": platform_image,
                            "imagePullPolicy": "IfNotPresent",
                            # Passed to entrypoint.sh as "$@": it migrates first, then
                            # execs these content-convergence commands. The last one
                            # claims registered packs' feature artifacts so they are
                            # acquired before any range needs them (ADR-034-R12).
                            "args": [
                                "/bin/sh",
                                "-c",
                                "python manage.py bootstrap_inbox_catalog"
                                " && python manage.py seed_raes_image_registry"
                                " && python manage.py acquire_feature_artifacts",
                            ],
                            "envFrom": [{"configMapRef": {"name": "platform-runtime"}}],
                            "env": [{"name": "SKIP_MIGRATIONS", "value": ""}],
                            "securityContext": {
                                "allowPrivilegeEscalation": False,
                                "capabilities": {"drop": ["ALL"]},
                            },
                        }
                    ],
                },
            },
        },
    }


def _delete_migration_job() -> None:
    """Delete the migration Job (idempotent; keeps the adopted SA + ConfigMap)."""
    run_cmd(["kubectl", "delete", "job", _MIGRATION_JOB, "--namespace", _PLATFORM_NAMESPACE, "--ignore-not-found"])


def _as_mapping(value: object) -> Mapping[str, object]:
    """Return ``value`` if it is a mapping, else an empty mapping (defensive projection)."""
    return value if isinstance(value, Mapping) else {}


def _migration_inputs(values: Mapping[str, object]) -> tuple[str, Mapping[str, object], Mapping[str, object], str]:
    """Extract and validate the migration Job inputs from the rendered chart values.

    Returns ``(migrator_role_arn, runtime_env, secret_refs, platform_image)``.
    """
    role_arns = _as_mapping(_as_mapping(values.get("identity")).get("serviceAccountRoleArns"))
    migrator_role_arn = role_arns.get(_MIGRATOR_SERVICE_ACCOUNT)
    if not migrator_role_arn:
        raise RuntimeError("render_aws_values did not provide the migrator service-account role ARN")
    platform_image = str(_as_mapping(values.get("images")).get("platform") or "")
    if not platform_image:
        raise RuntimeError("render_aws_values did not provide the platform image for the migration Job")
    runtime_env = _as_mapping(values.get("runtimeEnv"))
    secret_refs = _as_mapping(_as_mapping(values.get("runtime")).get("secretReferences"))
    return str(migrator_role_arn), runtime_env, secret_refs, platform_image


def _run_database_migrations(values: Mapping[str, object]) -> None:
    """Run schema migrations + content bootstrap once, before the chart install.

    AWS has no cloud-managed migration hook, so this dedicated Job is the single
    migrator (GCP parity). Deployed pods carry ``SKIP_MIGRATIONS=1`` and must not
    migrate on startup -- per-pod migrations made the provisioner-launcher's startup
    exceed its liveness window under DB load and crash-loop (#1826). It also converges
    the in-box scenario catalog and the ``provider=aws`` RAES image registry so a fresh
    tenant's smoke scenario resolves its package and AMIs.
    """
    migrator_role_arn, runtime_env, secret_refs, platform_image = _migration_inputs(values)

    prerequisites = _migration_prerequisites(
        migrator_role_arn=migrator_role_arn,
        runtime_env=runtime_env,
        secret_refs=secret_refs,
    )
    job = _migration_job(platform_image)
    # A completed Job's pod template is immutable, so clear any prior run first.
    _delete_migration_job()
    # Stream the manifests to kubectl over stdin rather than a temp file: the
    # platform-runtime ConfigMap carries the APP_SECRET_ID/DB_SECRET_ID references,
    # so no secret-bearing manifest is written to disk.
    for manifest in (prerequisites, job):
        return_code = run_cmd_secret_stdin(
            ["kubectl", "apply", "-f", "-"],
            secret_stdin=json.dumps(manifest),
        )
        if return_code != 0:
            raise RuntimeError("platform database migration prerequisites/Job apply failed")

    waited = run_cmd(
        [
            "kubectl",
            "wait",
            _KUBECTL_WAIT_FOR_COMPLETE,
            f"job/{_MIGRATION_JOB}",
            "--namespace",
            _PLATFORM_NAMESPACE,
            "--timeout=900s",
        ],
        check=False,
    )
    # Surface the pod logs (the commands redact secrets) regardless of outcome.
    run_cmd(
        ["kubectl", "logs", f"job/{_MIGRATION_JOB}", "--namespace", _PLATFORM_NAMESPACE, "--tail", "120"],
        check=False,
    )
    if waited is None or waited.returncode != 0:
        raise RuntimeError("platform database migration Job did not complete successfully")
    _delete_migration_job()


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
