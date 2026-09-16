"""Installed preparation admission enforces the actual neutral runner's Job shape."""

from copy import deepcopy
from uuid import uuid4

import pytest
from celpy import Environment, celtypes, json_to_cel

from shared.cloud.kubernetes._job_manifest import _build_env, _build_job
from shared.cloud.preparation_installation import PreparationInstallation, render_preparation_installation
from shared.cloud.preparation_runtime import preparation_task
from tests.shared.test_preparation_grant import grant_configuration


class ManifestClient:
    """Replace only optional SDK constructors; the real runner supplies every field."""

    def __getattr__(self, name):
        def resource(**fields):
            return {
                key.split("_")[0] + "".join(part.title() for part in key.split("_")[1:]): value
                for key, value in fields.items()
                if value is not None
            }

        return resource


client = ManifestClient()


def installation_fixture():
    return PreparationInstallation.model_validate(
        {
            "grant": grant_configuration(),
            "platform_namespace": "shifter-platform",
            "network_cidr": "10.240.0.0/24",
            "cluster_name": "test-cluster",
            "cluster_location": "us-central1",
            "controller_secret_ids": {
                key: "test-" + key.lower() for key in ("DB_SECRET_ID", "APP_SECRET_ID", "REDIS_SECRET_ID")
            },
            "controller_image": "registry.example/private/portal@sha256:" + "9" * 64,
            "service_accounts": {
                role: f"preparation-{role}@test-project.iam.gserviceaccount.com"
                for role in ("builder", "verifier", "cleanup", "controller")
            },
        }
    )


def test_controller_can_read_job_status_without_writing_it():
    role = next(item for item in render_preparation_installation(installation_fixture()) if item["kind"] == "Role")
    status_rules = [rule for rule in role["rules"] if "jobs/status" in rule["resources"]]
    assert status_rules == [{"apiGroups": ["batch"], "resources": ["jobs/status"], "verbs": ["get"]}]


def job_fixture(installation, phase="build"):
    grant = installation.grant
    image = (
        grant.cleanup_image
        if phase == "cleanup"
        else grant.approved_worker_images[0]
        if phase == "build"
        else grant.approved_verifier_images[0]
    )
    task = preparation_task(grant, phase, image, uuid4(), uuid4())
    env = _build_env(
        client,
        {
            "PREPARATION_OPERATION_ID": str(task.operation_id),
            "PREPARATION_ATTEMPT_ID": str(task.attempt_id),
            "PREPARATION_ENDPOINT": grant.worker_endpoint,
            "PREPARATION_TOKEN": "opaque-test-credential",
        },
        "artifact-preparation-secrets-" + "1" * 16,
    )
    return _build_job(client, image, "artifact-preparation", [], env, task.profile, task.identity)


def allows(policy, job, username=None):
    username = username or f"system:serviceaccount:shifter-platform:{installation_fixture().controller_name}"
    environment = Environment()
    activation = {
        "object": json_to_cel(job),
        "request": json_to_cel({"operation": "CREATE", "userInfo": {"username": username}}),
    }
    variables = {}
    for variable in policy["spec"]["variables"]:
        value = environment.program(environment.compile(variable["expression"])).evaluate(
            {**activation, "variables": celtypes.MapType(variables)}
        )
        variables[celtypes.StringType(variable["name"])] = value
    return all(
        environment.program(environment.compile(rule["expression"])).evaluate(
            {**activation, "variables": celtypes.MapType(variables)}
        )
        == celtypes.BoolType(True)
        for rule in policy["spec"]["validations"]
    )


@pytest.mark.parametrize("phase", ["build", "verify-inputs", "verify-output", "cleanup"])
def test_real_runner_job_is_accepted_for_each_installed_role(phase):
    installation = installation_fixture()
    resources = render_preparation_installation(installation)
    policy = next(item for item in resources if item["kind"] == "ValidatingAdmissionPolicy")
    assert allows(policy, job_fixture(installation, phase))


@pytest.mark.parametrize(
    "attack",
    [
        "actor",
        "image",
        "role",
        "command",
        "args",
        "extra-env",
        "endpoint",
        "literal-token",
        "volume",
        "privileged",
        "host-network",
        "sidecar",
        "init",
        "deadline",
        "parallel",
        "pull-secret",
        "node-pool",
        "node-name",
        "seccomp",
    ],
)
def test_unapproved_execution_cannot_use_preparation_cloud_authority(attack):
    installation = installation_fixture()
    policy = next(
        item for item in render_preparation_installation(installation) if item["kind"] == "ValidatingAdmissionPolicy"
    )
    job = deepcopy(job_fixture(installation))
    pod = job["spec"]["template"]["spec"]
    container = pod["containers"][0]
    username = f"system:serviceaccount:shifter-platform:{installation.controller_name}"
    execution_overrides = {
        "image": ("image", "foreign/image:latest"),
        "command": ("command", ["sh"]),
        "args": ("args", ["-c", "arbitrary"]),
    }
    pod_overrides = {
        "host-network": ("hostNetwork", True),
        "node-pool": ("nodeSelector", {"iam.gke.io/gke-metadata-server-enabled": "false"}),
        "node-name": ("nodeName", "unverified-node"),
    }
    security_overrides = {"privileged": ("privileged", True), "seccomp": ("seccompProfile", {"type": "Unconfined"})}
    if attack in execution_overrides:
        field, value = execution_overrides[attack]
        container[field] = value
    elif attack == "actor":
        username = "system:serviceaccount:shifter-platform:workers"
    elif attack == "role":
        pod["serviceAccountName"] = installation.grant.verifier_service_account
    elif attack == "extra-env":
        container["env"].append({"name": "PYTHONPATH", "value": "/untrusted"})
    elif attack == "endpoint":
        next(item for item in container["env"] if item["name"] == "PREPARATION_ENDPOINT")["value"] = (
            "https://foreign.invalid/"
        )
    elif attack == "literal-token":
        container["env"][-1] = {"name": "PREPARATION_TOKEN", "value": "literal"}
    elif attack == "volume":
        pod["volumes"] = [{"name": "tmp", "hostPath": {"path": "/"}}]
    elif attack in security_overrides:
        field, value = security_overrides[attack]
        container["securityContext"][field] = value
    elif attack in pod_overrides:
        field, value = pod_overrides[attack]
        pod[field] = value
    elif attack == "sidecar":
        pod["containers"].append(deepcopy(container))
    elif attack == "init":
        pod["initContainers"] = [deepcopy(container)]
    elif attack == "deadline":
        job["spec"]["activeDeadlineSeconds"] = 99999
    elif attack == "parallel":
        job["spec"]["parallelism"] = 10
    else:
        pod["imagePullSecrets"] = [{"name": "foreign"}]
    assert not allows(policy, job, username)


def test_installation_keeps_worker_identities_and_controller_privileges_separate():
    resources = render_preparation_installation(installation_fixture())
    accounts = [item for item in resources if item["kind"] == "ServiceAccount"]
    assert len(accounts) == 4
    role = next(item for item in resources if item["kind"] == "Role")
    assert all("*" not in rule["resources"] and "*" not in rule["verbs"] for rule in role["rules"])
    assert not any("create" in rule["verbs"] and "pods" in rule["resources"] for rule in role["rules"])
    assert not any(
        item["kind"] == "RoleBinding"
        and any(subject["name"] != installation_fixture().controller_name for subject in item["subjects"])
        for item in resources
    )
