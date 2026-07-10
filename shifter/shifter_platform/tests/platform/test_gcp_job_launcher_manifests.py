"""GCP job-launcher Kubernetes manifest invariants."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[4]
BASE_MANIFEST_DIR = REPO_ROOT / "platform" / "k8s" / "gcp" / "base"
CHART_DIR = REPO_ROOT / "platform" / "charts" / "shifter"
DEFAULT_NAMESPACE = "default"

JOB_LAUNCHER_DEPLOYMENTS = {
    "ctf-scheduler": "ctf-scheduler",
    "portal-web": "portal",
    "worker-engine": "workers",
}


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
PROVISIONER_LAUNCHER_USERNAME = "system:serviceaccount:shifter-platform:workers"
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

    assert {"create", "patch", "delete"} <= _verbs_for(role, "", "secrets"), (
        f"{source_name} job-launcher Role must grant create/patch/delete on secrets"
    )
    assert {"create", "delete"} <= _verbs_for(role, "batch", "jobs"), (
        f"{source_name} job-launcher Role must grant create and delete on jobs"
    )
