"""The GCP task adapter emits only the approved native database sidecar."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from shared.cloud.exceptions import CloudTaskError
from shared.cloud.gcp.task_runner import GCPTaskRunner, _build_gcp_task_profile
from shared.cloud.kubernetes._job_manifest import _build_job
from tests.shared.cloud.test_gcp_task_runner import _ApiException, _make_fake_k8s_client

PROXY_IMAGE = (
    "gcr.io/cloud-sql-connectors/cloud-sql-proxy@sha256:"
    "4f9071e7fb8bc0acc0c66dbbaa292d7c0e6337003ccd29f75e1431f8f8c3fce6"
)


def _native_settings(settings):
    settings.DB_AUTH_MODE = "cloud-sql-proxy"
    settings.CLOUD_SQL_INSTANCE_CONNECTION_NAME = "synthetic-project:us-central1:platform-pg"
    settings.ENGINE_TASK_SERVICE_ACCOUNT_NAME = "provisioner"


def test_gcp_native_sidecar_is_loopback_pinned_and_starts_before_the_job(settings):
    _native_settings(settings)
    client = _make_fake_k8s_client()
    for model in ("V1Probe", "V1HTTPGetAction", "V1ResourceRequirements"):
        setattr(client, model, lambda **kwargs: SimpleNamespace(**kwargs))
    job = _build_job(
        client, "provisioner:sha", "pulumi-provisioner", ["range", "provision"], None, _build_gcp_task_profile()
    )
    pod = job.spec.template.spec
    assert len(pod.containers) == 1
    assert len(pod.init_containers) == 1
    proxy = pod.init_containers[0]
    assert proxy.image == PROXY_IMAGE
    assert proxy.restart_policy == "Always"
    assert "--auto-iam-authn" in proxy.args
    assert "--private-ip" in proxy.args
    assert "--address=127.0.0.1" in proxy.args
    assert proxy.args[-1] == settings.CLOUD_SQL_INSTANCE_CONNECTION_NAME
    assert vars(proxy.startup_probe.http_get) == {"path": "/startup", "port": 9801}
    assert proxy.security_context.run_as_user == 65532
    assert proxy.security_context.allow_privilege_escalation is False
    assert proxy.security_context.read_only_root_filesystem is True
    assert not hasattr(proxy, "env") and not hasattr(proxy, "volume_mounts") and not hasattr(proxy, "command")


@pytest.mark.parametrize(
    "instance", ["", "some-project", "synthetic-project:us-central1:platform-pg --impersonate-service-account=operator"]
)
def test_proxy_instance_is_required_and_cannot_inject_arguments(settings, instance):
    _native_settings(settings)
    settings.CLOUD_SQL_INSTANCE_CONNECTION_NAME = instance
    with pytest.raises(CloudTaskError, match="Cloud SQL"):
        _build_gcp_task_profile()


@pytest.mark.parametrize("mutation", ["valid", "missing", "image", "args", "credentials", "security", "probe", "extra"])
def test_native_job_redelivery_rejects_changed_proxy(settings, mutation):
    _native_settings(settings)
    client = _make_fake_k8s_client()
    for model in ("V1Probe", "V1HTTPGetAction", "V1ResourceRequirements"):
        setattr(client, model, lambda **kwargs: SimpleNamespace(**kwargs))
    job = _build_job(
        client,
        "provisioner:sha",
        "pulumi-provisioner",
        ["range", "provision"],
        None,
        _build_gcp_task_profile(),
        task_identity="native-replay",
    )
    pod = job.spec.template.spec
    proxy = pod.init_containers[0]
    if mutation == "missing":
        pod.init_containers = []
    elif mutation == "image":
        proxy.image = "untrusted/proxy:latest"
    elif mutation == "args":
        proxy.args.append("--impersonate-service-account=operator")
    elif mutation == "credentials":
        proxy.env = [SimpleNamespace(name="GOOGLE_APPLICATION_CREDENTIALS", value="/credential/key")]
    elif mutation == "security":
        proxy.security_context.run_as_user = 0
    elif mutation == "probe":
        proxy.startup_probe.http_get.host = "external.invalid"
    elif mutation == "extra":
        pod.init_containers.append(SimpleNamespace(name="extra"))
    batch = MagicMock()
    batch.read_namespaced_job.return_value = job
    runner = GCPTaskRunner()
    runner._load_kubernetes_api = MagicMock(return_value=(batch, MagicMock(), client, _ApiException))
    if mutation == "valid":
        result = runner.run_task(
            task_definition="provisioner:sha",
            cluster="shifter-jobs",
            command=["range", "provision"],
            container_name="pulumi-provisioner",
            task_identity="native-replay",
        )
        assert result.startswith("shifter-jobs/pulumi-provisioner-")
        batch.create_namespaced_job.assert_not_called()
        return
    with pytest.raises(CloudTaskError, match="launch identity"):
        runner.run_task(
            task_definition="provisioner:sha",
            cluster="shifter-jobs",
            command=["range", "provision"],
            container_name="pulumi-provisioner",
            task_identity="native-replay",
        )
    batch.create_namespaced_job.assert_not_called()
