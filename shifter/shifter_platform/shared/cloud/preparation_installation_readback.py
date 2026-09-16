"""Read back the installed Kubernetes half of a preparation cloud grant."""

from collections.abc import Callable
from typing import Any, cast

from shared.cloud.preparation_installation import PreparationInstallation, render_preparation_installation


class KubernetesInstallationReader:
    """Use the operator's Kubernetes client without exposing any Secret payloads."""

    def __init__(self) -> None:
        from shared.cloud.kubernetes._client import load_kubernetes_api

        _, core, loaded_client, _ = load_kubernetes_api()
        client = cast(Any, loaded_client)
        self.client = client
        self.core = core
        self.api = client.ApiClient()

    def __call__(self, resource: dict[str, Any]) -> dict[str, Any]:
        methods = {
            "Namespace": (self.core, "read_namespace"),
            "ServiceAccount": (self.core, "read_namespaced_service_account"),
            "ConfigMap": (self.core, "read_namespaced_config_map"),
            "ResourceQuota": (self.core, "read_namespaced_resource_quota"),
            "Role": (self.client.RbacAuthorizationV1Api(), "read_namespaced_role"),
            "RoleBinding": (self.client.RbacAuthorizationV1Api(), "read_namespaced_role_binding"),
            "Deployment": (self.client.AppsV1Api(), "read_namespaced_deployment"),
            "NetworkPolicy": (self.client.NetworkingV1Api(), "read_namespaced_network_policy"),
            "ValidatingAdmissionPolicy": (self.client.AdmissionregistrationV1Api(), "read_validating_admission_policy"),
            "ValidatingAdmissionPolicyBinding": (
                self.client.AdmissionregistrationV1Api(),
                "read_validating_admission_policy_binding",
            ),
        }
        owner, name = methods[resource["kind"]]
        arguments = {key: value for key, value in resource["metadata"].items() if key in {"name", "namespace"}}
        try:
            response = getattr(owner, name)(**arguments, _request_timeout=30)
        except Exception as exc:
            raise ValueError("preparation Kubernetes installation readback failed") from exc
        return self.api.sanitize_for_serialization(response)


def verify_kubernetes_installation(
    configuration: PreparationInstallation,
    read: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> str:
    """Check deployed identities, admission, RBAC, budgets, isolation and controller rollout.

    This attests only Kubernetes resources. The installer must independently
    verify the matching cloud IAM/network before activating application authority.
    """
    reader = read or KubernetesInstallationReader()
    for expected in render_preparation_installation(configuration):
        observed = reader(expected)
        if not _contains(observed, expected):
            raise ValueError("preparation Kubernetes installation does not match its configuration")
        _verify_rollout_status(observed, expected["kind"])
    return configuration.digest


def _verify_rollout_status(observed: dict[str, Any], kind: str) -> None:
    """Handle verify rollout status."""
    status = observed.get("status", {})
    if kind in {"Deployment", "ValidatingAdmissionPolicy"} and status.get("observedGeneration") != observed[
        "metadata"
    ].get("generation"):
        raise ValueError("preparation installation has not converged")
    if kind == "ValidatingAdmissionPolicy" and (
        "typeChecking" not in status or status["typeChecking"].get("expressionWarnings")
    ):
        raise ValueError("preparation admission policy has not passed type checking")
    if kind == "Deployment" and (status.get("readyReplicas") != 1 or status.get("updatedReplicas") != 1):
        raise ValueError("preparation controller is not ready")


_EXECUTION_FIELDS = frozenset(
    {
        "command",
        "args",
        "initContainers",
        "ephemeralContainers",
        "hostNetwork",
        "hostPID",
        "hostIPC",
        "shareProcessNamespace",
        "hostUsers",
        "hostPath",
        "projected",
        "secret",
        "add",
        "privileged",
        "seLinuxOptions",
        "sysctls",
        "procMount",
        "dnsConfig",
        "hostAliases",
        "env",
        "envFrom",
        "valueFrom",
        "serviceAccountName",
        "automountServiceAccountToken",
        "matchExpressions",
    }
)


def _contains(observed: object, expected: object, field: str = "") -> bool:
    """Allow API defaults and status fields, but no additional list authorities."""
    if isinstance(expected, dict):
        return _contains_mapping(observed, expected, field)
    if isinstance(expected, list):
        return _contains_list(observed, expected, field)
    return observed == expected


def _contains_mapping(observed: object, expected: dict[str, Any], field: str) -> bool:
    """Handle contains mapping."""
    if not isinstance(observed, dict):
        return False
    observed = _mapping_api_defaults(observed, expected, field)
    exact_keys = not expected or field in {"labels", "matchLabels"}
    keys_match = not exact_keys or set(observed) == set(expected)
    no_extra_authority = not ((set(observed) - set(expected)) & _EXECUTION_FIELDS)
    return (
        keys_match
        and no_extra_authority
        and all(key in observed and _contains(observed[key], value, key) for key, value in expected.items())
    )


def _mapping_api_defaults(observed: dict[str, Any], expected: dict[str, Any], field: str) -> dict[str, Any]:
    """Normalize API omissions that are equivalent to explicit empty values."""
    # EnvVar.value and NetworkPolicy empty rule lists are API-default omissions.
    if field == "env" and expected.get("value") == "" and "value" not in observed:
        observed = dict(observed, value="")
    if field == "spec" and "policyTypes" in expected:
        observed = dict(observed)
        for key in ("ingress", "egress"):
            if expected.get(key) == [] and key not in observed:
                observed[key] = []
    return observed


def _contains_list(observed: object, expected: list[Any], field: str) -> bool:
    """Handle contains list."""
    return (
        isinstance(observed, list)
        and len(observed) == len(expected)
        and all(_contains(actual, wanted, field) for actual, wanted in zip(observed, expected, strict=True))
    )
