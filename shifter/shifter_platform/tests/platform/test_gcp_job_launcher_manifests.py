"""GCP job-launcher Kubernetes manifest invariants."""

from __future__ import annotations

import ast
import copy
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml
from celpy import CELEvalError, Environment, celtypes, json_to_cel

REPO_ROOT = Path(__file__).resolve().parents[4]
BASE_MANIFEST_DIR = REPO_ROOT / "platform" / "k8s" / "gcp" / "base"
CHART_DIR = REPO_ROOT / "platform" / "charts" / "shifter"
DEFAULT_NAMESPACE = "default"

JOB_LAUNCHER_DEPLOYMENTS = {"worker-provisioner-launcher": "provisioner-launcher"}


def _load_yaml_documents(source: str) -> list[dict[str, Any]]:
    return [document for document in yaml.safe_load_all(source) if isinstance(document, dict)]


def _load_base_documents() -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    for path in BASE_MANIFEST_DIR.glob("*.yaml"):
        documents.extend(_load_yaml_documents(path.read_text(encoding="utf-8")))
    return documents


def _load_helm_documents() -> list[dict[str, Any]]:
    helm = shutil.which("helm")
    if helm is None:
        pytest.skip("helm is required to validate rendered chart manifests")

    rendered = subprocess.run(  # noqa: S603
        [helm, "template", "shifter", str(CHART_DIR)],
        check=True,
        capture_output=True,
        text=True,
    )
    return _load_yaml_documents(rendered.stdout)


def _deployments(documents: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    deployments = {}
    for document in documents:
        if document.get("kind") != "Deployment":
            continue
        name = document["metadata"]["name"]
        deployments[name] = document
    return deployments


def _deployment_pod_spec(deployment: dict[str, Any]) -> dict[str, Any]:
    return deployment["spec"]["template"]["spec"]


def _metadata_namespace(document: dict[str, Any]) -> str:
    return document.get("metadata", {}).get("namespace", DEFAULT_NAMESPACE)


def _job_launcher_role(documents: list[dict[str, Any]]) -> dict[str, Any]:
    for document in documents:
        if document.get("kind") == "Role" and document.get("metadata", {}).get("name") == "job-launcher":
            return document
    raise AssertionError("job-launcher Role not found")


def _verbs_for(role: dict[str, Any], api_group: str, resource: str) -> set[str]:
    verbs: set[str] = set()
    for rule in role.get("rules", []):
        if api_group in rule.get("apiGroups", []) and resource in rule.get("resources", []):
            verbs.update(rule.get("verbs", []))
    return verbs


def _rbac_subjects(documents: list[dict[str, Any]]) -> set[tuple[str, str]]:
    subjects = set()
    for document in documents:
        if document.get("kind") != "RoleBinding":
            continue
        role_binding_namespace = _metadata_namespace(document)
        role_ref = document.get("roleRef", {})
        if role_ref.get("kind") != "Role" or role_ref.get("name") != "job-launcher":
            continue
        for subject in document.get("subjects", []):
            if subject.get("kind") == "ServiceAccount":
                subjects.add((subject.get("namespace", role_binding_namespace), subject["name"]))
    return subjects


# The canonical provisioner contract the admission policy pins. These must stay
# aligned with shared.cloud.PROVISIONER_CONTAINER_NAME, the provisioner KSA in
# platform/charts/shifter/values.yaml + platform/k8s/gcp/base/serviceaccounts.yaml,
# and the runtime ENGINE_TASK_IMAGE published in the platform-runtime ConfigMap.
PROVISIONER_POLICY_NAME = "restrict-provisioner-jobs"
PROVISIONER_SERVICE_ACCOUNT = "provisioner"
PROVISIONER_CONTAINER = "pulumi-provisioner"
PROVISIONER_LAUNCHER_USERNAME = "system:serviceaccount:shifter-platform:provisioner-launcher"
PROVISIONER_IMAGE_PARAM = "ENGINE_TASK_IMAGE"
RUNTIME_PARAM_CONFIGMAP = "platform-runtime"
PLATFORM_NAMESPACE = "shifter-platform"
JOBS_NAMESPACE = "shifter-jobs"


def _documents_by_kind(documents: list[dict[str, Any]], kind: str) -> dict[str, dict[str, Any]]:
    return {document["metadata"]["name"]: document for document in documents if document.get("kind") == kind}


def _policy(documents: list[dict[str, Any]]) -> dict[str, Any]:
    policies = _documents_by_kind(documents, "ValidatingAdmissionPolicy")
    assert PROVISIONER_POLICY_NAME in policies, (
        f"a ValidatingAdmissionPolicy named {PROVISIONER_POLICY_NAME!r} must gate provisioner Jobs"
    )
    return policies[PROVISIONER_POLICY_NAME]


def _binding(documents: list[dict[str, Any]]) -> dict[str, Any]:
    bindings = _documents_by_kind(documents, "ValidatingAdmissionPolicyBinding")
    assert PROVISIONER_POLICY_NAME in bindings, (
        f"a ValidatingAdmissionPolicyBinding named {PROVISIONER_POLICY_NAME!r} must bind the policy"
    )
    return bindings[PROVISIONER_POLICY_NAME]


def _policy_expressions(policy: dict[str, Any]) -> str:
    """All CEL text the policy evaluates (variables + validation expressions)."""
    spec = policy["spec"]
    variable_expressions = [variable.get("expression", "") for variable in spec.get("variables", [])]
    validation_expressions = [validation.get("expression", "") for validation in spec.get("validations", [])]
    return "\n".join(variable_expressions + validation_expressions)


def _policy_variable(policy: dict[str, Any], name: str) -> str:
    for variable in policy["spec"]["variables"]:
        if variable.get("name") == name:
            return variable["expression"]
    raise AssertionError(f"policy variable {name!r} not found")


_SEMANTIC_VALIDATION_MESSAGES = {
    "The provisioner-launcher service account may only create provisioner Jobs.",
    "Jobs running as the provisioner service account may only be created by the provisioner-launcher service account.",
    "A provisioner Job command must match the canonical operation and identifier argument grammar.",
    "A provisioner Job must carry its pinned image and canonical task identity annotations.",
    "A provisioner Job must use the configured image pull policy.",
    "A provisioner Job must remain a single non-indexed execution without alternate completion controls.",
    "A provisioner Job must use the four canonical bounded writable volumes.",
    "A provisioner Job must use the canonical writable volume mounts without subpaths.",
    "A provisioner Job must keep the canonical pod security and service-account token posture.",
    "A provisioner Job must not declare lifecycle hooks or container probes.",
    "A provisioner Job must carry the canonical Shifter labels.",
    "A provisioner Job environment must use the canonical literal and Secret-backed allowlists without duplicates.",
    "A provisioner Job must carry every required database and platform environment binding.",
    "A provisioner Job must disable retries with backoffLimit: 0.",
    "A provisioner Job must use ttlSecondsAfterFinished: 3600.",
}


def _semantic_policy_allows(
    policy: dict[str, Any],
    username: str,
    job: dict[str, Any],
    allowed_image: str,
    *,
    parameter_data: dict[str, str] | None = None,
) -> bool:
    """Evaluate the rendered policy's CEL, including its declared variables."""
    environment = Environment()
    if parameter_data is None:
        parameter_data = {
            PROVISIONER_IMAGE_PARAM: allowed_image,
            "ENGINE_TASK_IMAGE_PULL_POLICY": "Always",
        }
        for container in job.get("spec", {}).get("template", {}).get("spec", {}).get("containers", []):
            for entry in container.get("env", []):
                if "value" in entry:
                    parameter_data[entry["name"]] = entry["value"]
    base_activation = {
        "object": json_to_cel(job),
        "request": json_to_cel({"userInfo": {"username": username}}),
        "params": json_to_cel({"data": parameter_data}),
    }
    variables: dict[celtypes.StringType, Any] = {}
    try:
        for variable in policy["spec"]["variables"]:
            activation = {**base_activation, "variables": celtypes.MapType(variables)}
            value = environment.program(environment.compile(variable["expression"])).evaluate(activation)
            variables[celtypes.StringType(variable["name"])] = value
        activation = {**base_activation, "variables": celtypes.MapType(variables)}
        return all(
            bool(environment.program(environment.compile(validation["expression"])).evaluate(activation))
            for validation in policy["spec"]["validations"]
        )
    except CELEvalError:
        return False


def _canonical_admission_job() -> dict[str, Any]:
    labels = {
        "app.kubernetes.io/part-of": "shifter",
        "app.kubernetes.io/component": PROVISIONER_CONTAINER,
    }
    return {
        "metadata": {
            "labels": {**labels, "shifter.dev/task-runner": "gcp"},
            "annotations": {
                "shifter.dev/task-image": "registry.example/provisioner:sha",
                "shifter.dev/task-identity": "11111111-1111-1111-1111-111111111111",
            },
        },
        "spec": {
            "backoffLimit": 0,
            "ttlSecondsAfterFinished": 3600,
            "template": {
                "metadata": {"labels": labels},
                "spec": {
                    "serviceAccountName": PROVISIONER_SERVICE_ACCOUNT,
                    "automountServiceAccountToken": False,
                    "securityContext": {
                        "seccompProfile": {"type": "RuntimeDefault"},
                        "fsGroup": 1000,
                        "fsGroupChangePolicy": "OnRootMismatch",
                    },
                    "restartPolicy": "Never",
                    "volumes": [
                        {
                            "name": "provisioner-workspace",
                            "emptyDir": {"medium": "Memory", "sizeLimit": "256Mi"},
                        },
                        {"name": "tmp", "emptyDir": {}},
                        {"name": "tf-plugin-cache", "emptyDir": {}},
                        {"name": "pulumi-home", "emptyDir": {}},
                    ],
                    "containers": [
                        {
                            "name": PROVISIONER_CONTAINER,
                            "image": "registry.example/provisioner:sha",
                            "imagePullPolicy": "Always",
                            "args": ["range", "provision", "--request-id", "11111111-1111-1111-1111-111111111111"],
                            "securityContext": {
                                "readOnlyRootFilesystem": True,
                                "allowPrivilegeEscalation": False,
                                "runAsNonRoot": True,
                                "capabilities": {"drop": ["ALL"]},
                            },
                            "volumeMounts": [
                                {"name": "provisioner-workspace", "mountPath": "/var/run/provisioner/workspace"},
                                {"name": "tmp", "mountPath": "/tmp"},  # noqa: S108
                                {"name": "tf-plugin-cache", "mountPath": "/home/appuser/.terraform.d/plugin-cache"},
                                {"name": "pulumi-home", "mountPath": "/home/appuser/.pulumi"},
                            ],
                            "env": [
                                {"name": "CLOUD_PROVIDER", "value": "gcp"},
                                {"name": "ENVIRONMENT", "value": "gcp-dev"},
                                {"name": "DB_HOST", "value": "10.40.0.10"},
                                {"name": "DB_PORT", "value": "5432"},
                                {"name": "DB_NAME", "value": "shifter"},
                                {"name": "DB_USER", "value": "shifter"},
                                {
                                    "name": "DB_PASSWORD",
                                    "valueFrom": {
                                        "secretKeyRef": {
                                            "name": "pulumi-provisioner-secrets-0123456789abcdef",
                                            "key": "DB_PASSWORD",
                                        }
                                    },
                                },
                                {
                                    "name": "FIELD_ENCRYPTION_KEY",
                                    "valueFrom": {
                                        "secretKeyRef": {
                                            "name": "pulumi-provisioner-secrets-0123456789abcdef",
                                            "key": "FIELD_ENCRYPTION_KEY",
                                        }
                                    },
                                },
                            ],
                        }
                    ],
                },
            },
        },
    }


def _malformed_admission_job(canonical: dict[str, Any], mutation: str) -> dict[str, Any]:
    """Return one canonical Job with exactly one named invariant violated."""
    job = copy.deepcopy(canonical)
    pod_spec = job["spec"]["template"]["spec"]
    container = pod_spec["containers"][0]
    env = container["env"]
    mutators = {
        "operation": lambda: container["args"].__setitem__(1, "exec"),
        "extra-arg": lambda: container["args"].append("--unsafe"),
        "task-identity": lambda: job["metadata"]["annotations"].pop("shifter.dev/task-identity"),
        "image-pull-policy": lambda: container.__setitem__("imagePullPolicy", "IfNotPresent"),
        "literal-tamper": lambda: next(entry for entry in env if entry["name"] == "ENVIRONMENT").__setitem__(
            "value", "attacker"
        ),
        "missing-required": lambda: env.remove(next(entry for entry in env if entry["name"] == "DB_USER")),
        "parallelism": lambda: job["spec"].__setitem__("parallelism", 10),
        "volume": lambda: pod_spec["volumes"][0]["emptyDir"].__setitem__("sizeLimit", "10Gi"),
        "volume-mount": lambda: container["volumeMounts"][0].__setitem__("mountPath", "/app"),
        "image-pull-secret": lambda: pod_spec.__setitem__("imagePullSecrets", [{"name": "other-secret"}]),
        "pod-security": lambda: pod_spec["securityContext"].__setitem__("fsGroup", 2000),
        "token": lambda: pod_spec.__setitem__("automountServiceAccountToken", True),
        "lifecycle": lambda: container.__setitem__("lifecycle", {"postStart": {"exec": {"command": ["python"]}}}),
        "liveness": lambda: container.__setitem__("livenessProbe", {"exec": {"command": ["python"]}}),
        "readiness": lambda: container.__setitem__("readinessProbe", {"exec": {"command": ["python"]}}),
        "startup": lambda: container.__setitem__("startupProbe", {"exec": {"command": ["python"]}}),
        "labels": lambda: job["metadata"]["labels"].pop("shifter.dev/task-runner"),
        "secret": lambda: next(entry for entry in env if entry["name"] == "DB_PASSWORD")["valueFrom"][
            "secretKeyRef"
        ].__setitem__("name", "attacker-controlled-secret"),
        "unknown-literal": lambda: env.append({"name": "PULUMI_BACKEND_URL", "value": "https://attacker.invalid"}),
        "duplicate": lambda: env.append({"name": "ENVIRONMENT", "value": "attacker"}),
        "backoff": lambda: job["spec"].__setitem__("backoffLimit", 6),
        "ttl": lambda: job["spec"].__setitem__("ttlSecondsAfterFinished", 86400),
    }
    mutators[mutation]()
    return job


@pytest.mark.parametrize(
    ("source_name", "loader"),
    [
        ("base", _load_base_documents),
        ("helm", _load_helm_documents),
    ],
)
def test_provisioner_job_admission_policy_present(source_name: str, loader: Any) -> None:
    documents = loader()
    _policy(documents)  # asserts the policy is present
    binding = _binding(documents)

    assert binding["spec"]["policyName"] == PROVISIONER_POLICY_NAME, (
        f"{source_name} binding must reference the provisioner policy"
    )


@pytest.mark.parametrize(
    ("source_name", "loader"),
    [
        ("base", _load_base_documents),
        ("helm", _load_helm_documents),
    ],
)
def test_provisioner_job_admission_policy_invariants(source_name: str, loader: Any) -> None:
    documents = loader()
    policy = _policy(documents)
    binding = _binding(documents)

    # Fail closed: a CEL evaluation error must deny, not admit.
    assert policy["spec"]["failurePolicy"] == "Fail", f"{source_name} policy must fail closed"

    # The policy must constrain Job creation in the batch API group.
    match_rules = policy["spec"]["matchConstraints"]["resourceRules"]
    job_create_rule = any(
        "batch" in rule.get("apiGroups", [])
        and "jobs" in rule.get("resources", [])
        and "CREATE" in rule.get("operations", [])
        for rule in match_rules
    )
    assert job_create_rule, f"{source_name} policy must match batch/jobs CREATE"

    # Image pin is parameterised off a ConfigMap (the live platform-runtime one).
    assert policy["spec"]["paramKind"] == {"apiVersion": "v1", "kind": "ConfigMap"}, (
        f"{source_name} policy must take its image pin from a ConfigMap param"
    )

    # The CEL must mirror the full canonical GCPTaskRunner Job contract, not just
    # caller/image/identity. Pinning the image alone is insufficient: the caller
    # could keep the image and override the entrypoint, args, env, or volumes. We
    # assert on the literals so the policy cannot silently drop a constraint
    # without failing this test. Each needle maps to a denial case:
    #   provisioner SA gate; canonical submitter; container name; image pin;
    #   no command/entrypoint override; range/ngfw command family; no envFrom;
    #   emptyDir-only volumes; read-only-root-fs + drop-ALL security context;
    #   restartPolicy Never.
    expressions = _policy_expressions(policy)
    for needle in (
        f"'{PROVISIONER_SERVICE_ACCOUNT}'",
        PROVISIONER_LAUNCHER_USERNAME,
        f"'{PROVISIONER_CONTAINER}'",
        PROVISIONER_IMAGE_PARAM,
        "!has(c.command)",
        "'range'",
        "'aces-range'",
        "'ngfw'",
        "c.envFrom",
        "v.emptyDir",
        "readOnlyRootFilesystem",
        "'ALL'",
        "'Never'",
    ):
        assert needle in expressions, f"{source_name} policy CEL must reference {needle!r}"

    # Binding: hard deny, scoped to shifter-jobs, fail-closed on a missing param.
    assert binding["spec"]["validationActions"] == ["Deny"], f"{source_name} binding must Deny"
    param_ref = binding["spec"]["paramRef"]
    assert param_ref["name"] == RUNTIME_PARAM_CONFIGMAP
    assert param_ref["namespace"] == PLATFORM_NAMESPACE
    assert param_ref["parameterNotFoundAction"] == "Deny", f"{source_name} binding param must fail closed"
    namespace_selector = binding["spec"]["matchResources"]["namespaceSelector"]["matchLabels"]
    assert namespace_selector.get("kubernetes.io/metadata.name") == JOBS_NAMESPACE, (
        f"{source_name} binding must be scoped to the {JOBS_NAMESPACE} namespace"
    )


def test_provisioner_job_admission_policy_base_helm_equivalent() -> None:
    base_documents = _load_base_documents()
    helm_documents = _load_helm_documents()

    assert _policy(base_documents) == _policy(helm_documents), (
        "the provisioner admission policy must be identical in the static base and the Helm chart"
    )
    assert _binding(base_documents) == _binding(helm_documents), (
        "the provisioner admission policy binding must be identical in the static base and the Helm chart"
    )


def test_admission_environment_allowlists_match_task_runner_forwarding_contract() -> None:
    from engine.ecs import _GCP_PROVISIONER_ENV_KEYS
    from shared.cloud.sensitive_env import split_env

    policy = _policy(_load_base_documents())
    sensitive, plain = split_env(dict.fromkeys(_GCP_PROVISIONER_ENV_KEYS, "test-value"))

    assert set(ast.literal_eval(_policy_variable(policy, "allowedLiteralEnv"))) == set(plain)
    assert set(ast.literal_eval(_policy_variable(policy, "allowedSecretEnv"))) == set(sensitive)


def test_helm_admission_principal_tracks_launcher_identity_values() -> None:
    helm = shutil.which("helm")
    if helm is None:
        pytest.skip("helm is required to validate rendered chart manifests")
    rendered = subprocess.run(  # noqa: S603
        [
            helm,
            "template",
            "shifter",
            str(CHART_DIR),
            "--set",
            "namespaces.platform=custom-platform",
            "--set",
            "serviceAccounts.provisionerLauncher.name=custom-launcher",
            "--set",
            "namespaces.jobs=custom-jobs",
            "--set",
            "serviceAccounts.provisioner.name=custom-provisioner",
            "--set",
            "networkPolicy.kubernetesApiCidrs[0]=10.48.0.0/20",
            "--set",
            "runtimeEnv.ENGINE_TASK_NAMESPACE=wrong-jobs",
            "--set",
            "runtimeEnv.ENGINE_TASK_SERVICE_ACCOUNT_NAME=wrong-provisioner",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    documents = _load_yaml_documents(rendered.stdout)
    expressions = _policy_expressions(_policy(documents))
    binding = _binding(documents)
    runtime_config = _documents_by_kind(documents, "ConfigMap")[RUNTIME_PARAM_CONFIGMAP]
    api_egress = _documents_by_kind(documents, "NetworkPolicy")["allow-provisioner-launcher-kubernetes-api-egress"]

    assert "system:serviceaccount:custom-platform:custom-launcher" in expressions
    assert "custom-provisioner" in expressions
    assert binding["spec"]["paramRef"]["namespace"] == "custom-platform"
    assert (
        binding["spec"]["matchResources"]["namespaceSelector"]["matchLabels"]["kubernetes.io/metadata.name"]
        == "custom-jobs"
    )
    assert runtime_config["data"]["ENGINE_TASK_NAMESPACE"] == "custom-jobs"
    assert runtime_config["data"]["ENGINE_TASK_SERVICE_ACCOUNT_NAME"] == "custom-provisioner"
    assert api_egress["metadata"]["namespace"] == "custom-platform"
    assert api_egress["spec"]["podSelector"]["matchLabels"]["app.kubernetes.io/component"] == (
        "worker-provisioner-launcher"
    )
    assert api_egress["spec"]["egress"][0]["to"] == [{"ipBlock": {"cidr": "10.48.0.0/20"}}]
    assert api_egress["spec"]["egress"][0]["ports"] == [{"protocol": "TCP", "port": 443}]


@pytest.mark.parametrize("loader", [_load_base_documents, _load_helm_documents])
def test_admission_policy_semantically_denies_spoofed_and_malformed_launches(loader: Any) -> None:
    policy = _policy(loader())
    assert _SEMANTIC_VALIDATION_MESSAGES.issubset(
        {validation.get("message", "") for validation in policy["spec"]["validations"]}
    )
    canonical = _canonical_admission_job()
    image = "registry.example/provisioner:sha"
    parameters = {
        PROVISIONER_IMAGE_PARAM: image,
        "ENGINE_TASK_IMAGE_PULL_POLICY": "Always",
        "CLOUD_PROVIDER": "gcp",
        "ENVIRONMENT": "gcp-dev",
        "DB_HOST": "10.40.0.10",
        "DB_PORT": "5432",
        "DB_NAME": "shifter",
        "DB_USER": "shifter",
    }

    assert _semantic_policy_allows(policy, PROVISIONER_LAUNCHER_USERNAME, canonical, image, parameter_data=parameters)
    assert not _semantic_policy_allows(
        policy,
        "system:serviceaccount:shifter-platform:portal",
        canonical,
        image,
        parameter_data=parameters,
    )
    non_provisioner = copy.deepcopy(canonical)
    non_provisioner["spec"]["template"]["spec"]["serviceAccountName"] = "default"
    assert not _semantic_policy_allows(
        policy, PROVISIONER_LAUNCHER_USERNAME, non_provisioner, image, parameter_data=parameters
    )

    malformed_jobs = []
    for mutation in (
        "operation",
        "extra-arg",
        "task-identity",
        "image-pull-policy",
        "literal-tamper",
        "missing-required",
        "parallelism",
        "volume",
        "volume-mount",
        "image-pull-secret",
        "pod-security",
        "token",
        "lifecycle",
        "liveness",
        "readiness",
        "startup",
        "labels",
        "secret",
        "unknown-literal",
        "duplicate",
        "backoff",
        "ttl",
    ):
        malformed_jobs.append(_malformed_admission_job(canonical, mutation))

    assert all(
        not _semantic_policy_allows(
            policy,
            PROVISIONER_LAUNCHER_USERNAME,
            job,
            image,
            parameter_data=parameters,
        )
        for job in malformed_jobs
    )


@pytest.mark.parametrize(
    ("source_name", "loader"),
    [
        ("base", _load_base_documents),
        ("helm", _load_helm_documents),
    ],
)
def test_only_gcp_job_launchers_mount_service_account_tokens(
    source_name: str,
    loader: Any,
) -> None:
    documents = loader()
    deployments = _deployments(documents)
    token_mounting_deployments = {
        name
        for name, deployment in deployments.items()
        if _deployment_pod_spec(deployment).get("automountServiceAccountToken") is True
    }

    assert token_mounting_deployments == set(JOB_LAUNCHER_DEPLOYMENTS), (
        f"{source_name} must mount service account tokens only on GCP job-launching Deployments"
    )

    for deployment_name, service_account_name in JOB_LAUNCHER_DEPLOYMENTS.items():
        pod_spec = _deployment_pod_spec(deployments[deployment_name])
        assert pod_spec["serviceAccountName"] == service_account_name
        assert pod_spec["automountServiceAccountToken"] is True, (
            f"{source_name} {deployment_name} must mount its service account token "
            "so GCP task launching can use in-cluster Kubernetes auth"
        )

    for deployment_name, deployment in deployments.items():
        if deployment_name in JOB_LAUNCHER_DEPLOYMENTS:
            continue
        pod_spec = _deployment_pod_spec(deployment)
        assert pod_spec["automountServiceAccountToken"] is False, (
            f"{source_name} {deployment_name} must remain tokenless because it does not launch Kubernetes Jobs"
        )


@pytest.mark.parametrize(
    ("source_name", "loader"),
    [
        ("base", _load_base_documents),
        ("helm", _load_helm_documents),
    ],
)
def test_job_launcher_rbac_subjects_match_token_mounting_workloads(
    source_name: str,
    loader: Any,
) -> None:
    documents = loader()
    deployments = _deployments(documents)
    launcher_service_accounts = {
        (_metadata_namespace(deployments[name]), _deployment_pod_spec(deployments[name])["serviceAccountName"])
        for name in JOB_LAUNCHER_DEPLOYMENTS
    }

    assert _rbac_subjects(documents) == launcher_service_accounts, (
        f"{source_name} job-launcher RBAC subjects must exactly match the workloads "
        "that mount service account tokens for Kubernetes Job creation"
    )


@pytest.mark.parametrize("loader", [_load_base_documents, _load_helm_documents])
def test_portal_scheduler_and_general_workers_cannot_mutate_provisioner_objects(loader: Any) -> None:
    documents = loader()
    subjects = _rbac_subjects(documents)
    forbidden = {
        (PLATFORM_NAMESPACE, "portal"),
        (PLATFORM_NAMESPACE, "ctf-scheduler"),
        (PLATFORM_NAMESPACE, "workers"),
    }
    assert subjects.isdisjoint(forbidden)

    launcher = (PLATFORM_NAMESPACE, "provisioner-launcher")
    assert subjects == {launcher}


@pytest.mark.parametrize(
    ("source_name", "loader"),
    [
        ("base", _load_base_documents),
        ("helm", _load_helm_documents),
    ],
)
def test_job_launcher_role_grants_per_job_secret_lifecycle(
    source_name: str,
    loader: Any,
) -> None:
    """The launcher Role must allow the per-Job Secret lifecycle (issue #1185).

    The GCP task runner creates a per-Job Secret for sensitive env vars, patches
    it with the Job ownerReference, and deletes it on the unwind path; it also
    deletes the Job when owner-reference installation fails. Without these verbs
    range launch fails at create_namespaced_secret with a 403.
    """
    role = _job_launcher_role(loader())

    assert _verbs_for(role, "", "secrets") == {"create", "patch", "delete"}, (
        f"{source_name} job-launcher Role must grant create/patch/delete on secrets"
    )
    assert _verbs_for(role, "batch", "jobs") == {"create", "get", "delete"}, (
        f"{source_name} job-launcher Role must grant only create/get/delete on jobs"
    )
    assert _verbs_for(role, "", "pods") == set(), f"{source_name} launcher must not receive Pod read access"
