"""Behavior tests for the GCP task-runner configuration in engine.ecs.

GCP uses Kubernetes namespace/image settings and omits the AWS network config.
These drive the real configuration units that ``_start_ecs_task`` consumes for
GCP (``_get_engine_task_config`` and ``_get_gcp_provisioner_env_overrides``)
rather than patching ``get_task_runner``; that captures the same contract (no
network config, the GKE provisioner env, the #762 password exclusions) against
the real logic.
"""

import os
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import UUID

GCP_ENV = {
    "ENVIRONMENT": "gcp-dev",
    "CLOUD_PROVIDER": "gcp",
    "CLOUD_REGION": "us-central1",
    "GCP_REGION": "us-central1",
    "GCP_PROJECT_ID": "shifter-gcp-dev",
    "GOOGLE_CLOUD_PROJECT": "shifter-gcp-dev",
    "DB_HOST": "10.0.0.10",
    "DB_PORT": "5432",
    "DB_NAME": "shifter",
    "DB_USER": "shifter",
    "DB_PASSWORD": "secret",
    "RANGE_EVENTS_TOPIC_ID": "projects/shifter-gcp-dev/topics/shifter-gcp-dev-events",
    "RANGE_NETWORK_ID": "projects/shifter-gcp-dev/global/networks/shifter-gcp-dev-range",
    "RANGE_NETWORK_CIDR": "10.50.0.0/16",
    "PORTAL_NETWORK_CIDRS": "10.40.0.0/20,10.44.0.0/16",
    "GCP_RANGE_BACKEND": "gdc",
    "GDC_ACCESS_SECRET_ID": "projects/shifter-gcp-dev/secrets/shifter-gcp-dev-gdc-access",
    "GDC_VM_IMAGE_GCS_SECRET_ID": "projects/shifter-gcp-dev/secrets/shifter-gcp-dev-gdc-vm-image-gcs",
    "GDC_KALI_IMAGE_URL": "gs://images/kali.qcow2",
    "GDC_SETUP_RUNNER_IMAGE": "us-central1-docker.pkg.dev/shifter-gcp-dev/runner:abc123",
    "ENGINE_TASK_IMAGE": "us-central1-docker.pkg.dev/shifter-gcp-dev/pulumi-provisioner:abc123",
    # Shared guest passwords MUST NOT flow into the provisioner env after #762;
    # they are set here to prove they are filtered out, not forwarded.
    "GDC_WINDOWS_ADMIN_PASSWORD": "WinPass!",
    "GDC_KALI_PASSWORD": "KaliPass!",
    "GDC_UBUNTU_PASSWORD": "UbuntuPass!",
    # DC_DOMAIN_PASSWORD remains deployment-scoped and is forwarded.
    "DC_DOMAIN_PASSWORD": "DomainAdminPass!",
}


def _configure_gcp_task_settings(settings):
    settings.CLOUD_PROVIDER = "gcp"
    settings.LOCAL_PROVISIONER = None
    settings.ENGINE_TASK_CLUSTER = "shifter-jobs"
    settings.ENGINE_TASK_DEFINITION = GCP_ENV["ENGINE_TASK_IMAGE"]
    settings.ENGINE_ECS_CLUSTER_ARN = ""
    settings.ENGINE_TASK_DEFINITION_ARN = ""


class _KubeModel(SimpleNamespace):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)


def _install_fake_kubernetes(monkeypatch):
    batch_api = MagicMock()
    core_api = MagicMock()
    created_jobs = [
        SimpleNamespace(metadata=SimpleNamespace(name="job-range-legacy", uid="uid-range-legacy")),
        SimpleNamespace(metadata=SimpleNamespace(name="job-range-request", uid="uid-range-request")),
        SimpleNamespace(metadata=SimpleNamespace(name="job-ngfw", uid="uid-ngfw")),
    ]
    batch_api.create_namespaced_job.side_effect = created_jobs
    client = SimpleNamespace(
        BatchV1Api=MagicMock(return_value=batch_api),
        CoreV1Api=MagicMock(return_value=core_api),
        exceptions=SimpleNamespace(ApiException=Exception),
        V1Capabilities=_KubeModel,
        V1Container=_KubeModel,
        V1EmptyDirVolumeSource=_KubeModel,
        V1EnvVar=_KubeModel,
        V1EnvVarSource=_KubeModel,
        V1Job=_KubeModel,
        V1JobSpec=_KubeModel,
        V1ObjectMeta=_KubeModel,
        V1OwnerReference=_KubeModel,
        V1PodSecurityContext=_KubeModel,
        V1PodSpec=_KubeModel,
        V1PodTemplateSpec=_KubeModel,
        V1Secret=_KubeModel,
        V1SecretKeySelector=_KubeModel,
        V1SeccompProfile=_KubeModel,
        V1SecurityContext=_KubeModel,
        V1Volume=_KubeModel,
        V1VolumeMount=_KubeModel,
    )
    config = SimpleNamespace(
        load_kube_config=MagicMock(),
        load_incluster_config=MagicMock(),
        config_exception=SimpleNamespace(ConfigException=Exception),
    )
    kubernetes = ModuleType("kubernetes")
    kubernetes.client = client
    kubernetes.config = config
    monkeypatch.setitem(sys.modules, "kubernetes", kubernetes)
    return batch_api, core_api


def _job_container(job):
    return job.spec.template.spec.containers[0]


def _literal_env(container):
    return {item.name: item.value for item in container.env if getattr(item, "value", None) is not None}


class TestGcpTaskConfig:
    def test_omits_network_config_for_gcp(self, settings):
        from engine.ecs import _get_engine_task_config

        settings.CLOUD_PROVIDER = "gcp"
        settings.ENGINE_TASK_CLUSTER = "shifter-jobs"
        settings.ENGINE_TASK_DEFINITION = (
            "us-central1-docker.pkg.dev/shifter-gcp-dev/shifter-gcp-dev-pulumi-provisioner:latest"
        )

        cluster, task_definition, network_config = _get_engine_task_config()
        assert cluster == "shifter-jobs"
        assert task_definition.endswith("pulumi-provisioner:latest")
        assert network_config is None


class TestGcpProvisionerEnvOverrides:
    def test_returns_none_for_non_gcp(self, settings):
        from engine.ecs import _get_gcp_provisioner_env_overrides

        settings.CLOUD_PROVIDER = "aws"
        assert _get_gcp_provisioner_env_overrides() is None

    def test_forwards_gke_runtime_contract(self, settings):
        from engine.ecs import _get_gcp_provisioner_env_overrides

        settings.CLOUD_PROVIDER = "gcp"
        with patch.dict(os.environ, GCP_ENV, clear=False):
            overrides = _get_gcp_provisioner_env_overrides()

        assert overrides["RANGE_NETWORK_ID"] == GCP_ENV["RANGE_NETWORK_ID"]
        assert overrides["RANGE_NETWORK_CIDR"] == GCP_ENV["RANGE_NETWORK_CIDR"]
        assert overrides["PORTAL_NETWORK_CIDRS"] == GCP_ENV["PORTAL_NETWORK_CIDRS"]
        assert overrides["GCP_RANGE_BACKEND"] == GCP_ENV["GCP_RANGE_BACKEND"]
        assert overrides["GDC_ACCESS_SECRET_ID"] == GCP_ENV["GDC_ACCESS_SECRET_ID"]
        assert overrides["GDC_VM_IMAGE_GCS_SECRET_ID"] == GCP_ENV["GDC_VM_IMAGE_GCS_SECRET_ID"]
        assert overrides["GDC_KALI_IMAGE_URL"] == GCP_ENV["GDC_KALI_IMAGE_URL"]
        # The in-range guest setup-runner image (and the provisioner's own image
        # as the default) must reach the provision Job for RangePodSSHExecutor.
        assert overrides["GDC_SETUP_RUNNER_IMAGE"] == GCP_ENV["GDC_SETUP_RUNNER_IMAGE"]
        assert overrides["ENGINE_TASK_IMAGE"] == GCP_ENV["ENGINE_TASK_IMAGE"]
        assert overrides["DB_HOST"] == GCP_ENV["DB_HOST"]

    def test_forwards_gce_range_cell_runtime_contract(self, settings):
        from engine.ecs import _get_gcp_provisioner_env_overrides

        settings.CLOUD_PROVIDER = "gcp"
        gce_env = {
            **GCP_ENV,
            "GCP_RANGE_BACKEND": "gce",
            "GCP_RANGE_CELL_NETWORK_MODE": "vpc-per-range",
            "RANGE_NETWORK_ZONE": "us-central1-b",
            "GCP_RANGE_HOST_SERVICE_ACCOUNT_EMAIL": "range-host@shifter-gcp-dev.iam.gserviceaccount.com",
            "GCP_RANGE_LINUX_IMAGE": "projects/debian-cloud/global/images/family/debian-12",
            "GCP_RANGE_KALI_IMAGE": "projects/kali/global/images/kali",
            "GCP_RANGE_WINDOWS_IMAGE": "projects/windows-cloud/global/images/family/windows-2022",
            "GCP_RANGE_DC_IMAGE": "projects/windows-cloud/global/images/family/windows-2022",
            "GCP_RANGE_EGRESS_ALLOW_CIDRS": "10.60.0.0/16",
        }

        with patch.dict(os.environ, gce_env, clear=False):
            overrides = _get_gcp_provisioner_env_overrides()

        assert overrides["GCP_RANGE_BACKEND"] == "gce"
        assert overrides["GCP_RANGE_CELL_NETWORK_MODE"] == "vpc-per-range"
        assert overrides["RANGE_NETWORK_ZONE"] == "us-central1-b"
        assert overrides["GCP_RANGE_HOST_SERVICE_ACCOUNT_EMAIL"] == "range-host@shifter-gcp-dev.iam.gserviceaccount.com"
        assert overrides["GCP_RANGE_LINUX_IMAGE"] == "projects/debian-cloud/global/images/family/debian-12"
        assert overrides["GCP_RANGE_EGRESS_ALLOW_CIDRS"] == "10.60.0.0/16"

    def test_excludes_shared_guest_passwords(self, settings):
        from engine.ecs import _get_gcp_provisioner_env_overrides

        settings.CLOUD_PROVIDER = "gcp"
        with patch.dict(os.environ, GCP_ENV, clear=False):
            overrides = _get_gcp_provisioner_env_overrides()

        # #762: shared guest passwords are per-instance secrets, never forwarded.
        assert "GDC_WINDOWS_ADMIN_PASSWORD" not in overrides
        assert "GDC_KALI_PASSWORD" not in overrides
        assert "GDC_UBUNTU_PASSWORD" not in overrides
        # The deployment-scoped DC domain password is still forwarded.
        assert overrides["DC_DOMAIN_PASSWORD"] == GCP_ENV["DC_DOMAIN_PASSWORD"]


class TestGcpTaskDispatch:
    def test_public_start_functions_dispatch_with_gcp_env_overrides(self, settings, monkeypatch):
        from engine.ecs import (
            PROVISIONER_CONTAINER_NAME,
            _get_gcp_provisioner_env_overrides,
            start_ngfw_provisioning,
            start_provisioning,
            start_range_provisioning,
        )

        _configure_gcp_task_settings(settings)
        range_request_id = UUID("11111111-1111-1111-1111-111111111111")
        ngfw_request_id = UUID("22222222-2222-2222-2222-222222222222")
        batch_api, core_api = _install_fake_kubernetes(monkeypatch)

        with patch.dict(os.environ, GCP_ENV, clear=True):
            expected_env = _get_gcp_provisioner_env_overrides()
            assert start_provisioning(range_id=42, user_id=7) == "shifter-jobs/job-range-legacy"
            assert start_range_provisioning(range_request_id) == "shifter-jobs/job-range-request"
            assert start_ngfw_provisioning(ngfw_request_id) == "shifter-jobs/job-ngfw"

        assert expected_env is not None
        assert "GDC_WINDOWS_ADMIN_PASSWORD" not in expected_env
        assert batch_api.create_namespaced_job.call_count == 3
        assert core_api.create_namespaced_secret.call_count == 3
        jobs = [call.kwargs["body"] for call in batch_api.create_namespaced_job.call_args_list]
        assert [call.kwargs["namespace"] for call in batch_api.create_namespaced_job.call_args_list] == [
            "shifter-jobs",
            "shifter-jobs",
            "shifter-jobs",
        ]
        assert [_job_container(job).args for job in jobs] == [
            ["range", "provision", "--range-id", "42", "--user-id", "7"],
            ["range", "provision", "--request-id", str(range_request_id)],
            ["ngfw", "provision", "--request-id", str(ngfw_request_id)],
        ]
        assert [_job_container(job).name for job in jobs] == [PROVISIONER_CONTAINER_NAME] * 3
        assert [_job_container(job).image for job in jobs] == [GCP_ENV["ENGINE_TASK_IMAGE"]] * 3
        first_env = _literal_env(_job_container(jobs[0]))
        assert first_env["GCP_RANGE_BACKEND"] == "gdc"
        assert first_env["RANGE_NETWORK_ID"] == GCP_ENV["RANGE_NETWORK_ID"]
        assert "DB_PASSWORD" not in first_env
