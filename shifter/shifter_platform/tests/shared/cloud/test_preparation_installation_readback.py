"""A rendered configuration is not evidence of a running, restricted installation."""

from copy import deepcopy

import pytest

from shared.cloud.preparation_installation import render_preparation_installation
from shared.cloud.preparation_installation_readback import verify_kubernetes_installation
from tests.shared.cloud.test_preparation_installation import installation_fixture


def observed_fixture(configuration=None):
    configuration = configuration or installation_fixture()
    resources = render_preparation_installation(configuration)
    observed = {}
    for resource in resources:
        row = deepcopy(resource)
        row["metadata"]["generation"] = 1
        if row["kind"] == "Deployment":
            row["status"] = {"observedGeneration": 1, "readyReplicas": 1, "updatedReplicas": 1}
        elif row["kind"] == "ValidatingAdmissionPolicy":
            row["status"] = {"observedGeneration": 1, "typeChecking": {}}
        observed[(row["kind"], row["metadata"]["name"])] = row
    return configuration, observed


@pytest.mark.parametrize(
    "failure",
    [
        None,
        "role",
        "missing",
        "warning",
        "stale",
        "unready",
        "cloud-identity",
        "network-selector",
        "controller-command",
    ],
)
def test_installer_requires_actual_policy_rbac_rollout_and_workload_identity(failure):
    configuration, observed = observed_fixture()
    if failure == "role":
        observed[("Role", "preparation-controller")]["rules"].append(
            {"apiGroups": ["*"], "resources": ["*"], "verbs": ["*"]}
        )
    elif failure == "missing":
        observed.pop(("ResourceQuota", "preparation-budget"))
    elif failure == "warning":
        observed[("ValidatingAdmissionPolicy", configuration.grant.namespace)]["status"]["typeChecking"] = {
            "expressionWarnings": [{"warning": "invalid expression"}]
        }
    elif failure == "stale":
        observed[("ValidatingAdmissionPolicy", configuration.grant.namespace)]["status"]["observedGeneration"] = 0
    elif failure == "unready":
        observed[("Deployment", configuration.controller_name)]["status"]["readyReplicas"] = 0
    elif failure == "cloud-identity":
        observed[("ServiceAccount", "preparation-builder")]["metadata"]["annotations"][
            "iam.gke.io/gcp-service-account"
        ] = "foreign@example.invalid"

    if failure == "network-selector":
        observed[("NetworkPolicy", "preparation-workers")]["spec"]["podSelector"] = {
            "matchLabels": {"other": "workload"}
        }
    elif failure == "controller-command":
        observed[("Deployment", configuration.controller_name)]["spec"]["template"]["spec"]["containers"][0][
            "command"
        ] = ["arbitrary"]

    def read(resource):
        return observed.get((resource["kind"], resource["metadata"]["name"]))

    if failure:
        with pytest.raises(ValueError):
            verify_kubernetes_installation(configuration, read)
    else:
        assert verify_kubernetes_installation(configuration, read) == configuration.digest


@pytest.mark.parametrize("secret_override", [False, True])
def test_api_omitted_empty_environment_value_cannot_hide_secret_override(secret_override):
    configuration, observed = observed_fixture()
    container = observed[("Deployment", configuration.controller_name)]["spec"]["template"]["spec"]["containers"][0]
    empty = next(item for item in container["env"] if item.get("value") == "")
    empty.pop("value")  # Kubernetes omits the default empty EnvVar.value on readback.
    if secret_override:
        empty["valueFrom"] = {"secretKeyRef": {"name": "unapproved", "key": "credential"}}

    def read(resource):
        return observed.get((resource["kind"], resource["metadata"]["name"]))

    if secret_override:
        with pytest.raises(ValueError):
            verify_kubernetes_installation(configuration, read)
    else:
        assert verify_kubernetes_installation(configuration, read) == configuration.digest


@pytest.mark.parametrize("allow_ingress", [False, True])
def test_api_omitted_deny_all_ingress_cannot_hide_allow_rule(allow_ingress):
    configuration, observed = observed_fixture()
    policy = observed[("NetworkPolicy", "preparation-workers")]["spec"]
    policy.pop("ingress")  # Empty lists are omitted; policyTypes still includes Ingress.
    if allow_ingress:
        policy["ingress"] = [{}]

    def read(resource):
        return observed.get((resource["kind"], resource["metadata"]["name"]))

    if allow_ingress:
        with pytest.raises(ValueError):
            verify_kubernetes_installation(configuration, read)
    else:
        assert verify_kubernetes_installation(configuration, read) == configuration.digest
