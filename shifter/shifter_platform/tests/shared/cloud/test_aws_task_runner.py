"""Tests for the EKS-native AWS Kubernetes task runner (#1826).

The AWS provisioner dispatches as a Kubernetes Job, mirroring GCP. These tests
reuse the fake-``kubernetes.client`` helpers from ``test_gcp_task_runner`` and
assert the AWS-specific wiring: the ``shifter.dev/task-runner: aws`` label, the
IRSA service account, and that the shared provisioner hardening posture is
applied. The generic Job mechanics are covered by the neutral-runner tests.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from shared.cloud import PROVISIONER_CONTAINER_NAME
from shared.cloud.aws.task_runner import AWSKubernetesTaskRunner, _build_aws_task_profile
from shared.cloud.exceptions import CloudTaskError

from .test_gcp_task_runner import _ApiException, _make_fake_k8s_client

_AWS_IMAGE = "123456789012.dkr.ecr.us-east-2.amazonaws.com/shifter/pulumi-provisioner:sha-abc123"


class TestAWSTaskProfile:
    def test_profile_stamps_aws_runner_label_and_irsa_service_account(self, settings) -> None:
        settings.ENGINE_TASK_SERVICE_ACCOUNT_NAME = "provisioner"
        profile = _build_aws_task_profile()
        assert profile.runner_label_value == "aws"
        assert profile.service_account_name == "provisioner"
        assert profile.hardening is not None
        assert profile.hardening.container_name == PROVISIONER_CONTAINER_NAME

    def test_aws_and_gcp_runner_labels_are_distinct(self) -> None:
        from shared.cloud.gcp.task_runner import _build_gcp_task_profile

        assert _build_aws_task_profile().runner_label_value != _build_gcp_task_profile().runner_label_value


class TestAWSKubernetesTaskRunnerRunTask:
    def test_creates_namespaced_job_with_aws_runner_label(self, settings) -> None:
        settings.ENGINE_TASK_SERVICE_ACCOUNT_NAME = "provisioner"
        settings.ENGINE_TASK_IMAGE_PULL_POLICY = "Always"
        settings.ENGINE_TASK_BACKOFF_LIMIT = 0
        settings.ENGINE_TASK_TTL_SECONDS_AFTER_FINISHED = 3600

        batch_api = MagicMock()
        batch_api.create_namespaced_job.return_value = SimpleNamespace(metadata=SimpleNamespace(name="job-aws-1"))
        runner = AWSKubernetesTaskRunner()
        runner._load_kubernetes_api = MagicMock(
            return_value=(batch_api, MagicMock(), _make_fake_k8s_client(), _ApiException)
        )

        task_id = runner.run_task(
            task_definition=_AWS_IMAGE,
            cluster="shifter-jobs",
            command=["range", "provision", "--range-id", "42"],
            container_name=PROVISIONER_CONTAINER_NAME,
            env_overrides={"CLOUD_PROVIDER": "aws"},
        )

        assert task_id == "shifter-jobs/job-aws-1"
        call_kwargs = batch_api.create_namespaced_job.call_args.kwargs
        assert call_kwargs["namespace"] == "shifter-jobs"
        job = call_kwargs["body"]
        # The AWS runner stamps its own provider tag so the fail-closed admission
        # policy binds AWS Jobs to the AWS contract, never the GCP one.
        assert job.metadata.labels["shifter.dev/task-runner"] == "aws"
        assert job.spec.template.spec.containers[0].image == _AWS_IMAGE
        assert job.spec.template.spec.containers[0].image_pull_policy == "Always"

    def test_provisioner_container_keeps_shared_hardening_posture(self, settings) -> None:
        settings.ENGINE_TASK_SERVICE_ACCOUNT_NAME = "provisioner"

        batch_api = MagicMock()
        batch_api.create_namespaced_job.return_value = SimpleNamespace(metadata=SimpleNamespace(name="job-aws-2"))
        runner = AWSKubernetesTaskRunner()
        runner._load_kubernetes_api = MagicMock(
            return_value=(batch_api, MagicMock(), _make_fake_k8s_client(), _ApiException)
        )

        runner.run_task(
            task_definition=_AWS_IMAGE,
            cluster="shifter-jobs",
            command=["range", "provision", "--range-id", "42"],
            container_name=PROVISIONER_CONTAINER_NAME,
        )

        pod_spec = batch_api.create_namespaced_job.call_args.kwargs["body"].spec.template.spec
        assert pod_spec.service_account_name == "provisioner"
        assert pod_spec.restart_policy == "Never"
        assert pod_spec.automount_service_account_token is False

        container = pod_spec.containers[0]
        sc = container.security_context
        assert sc.read_only_root_filesystem is True
        assert sc.run_as_non_root is True
        assert sc.run_as_user == 1000
        assert sc.run_as_group == 1000
        assert sc.allow_privilege_escalation is False
        assert sc.capabilities.drop == ["ALL"]

        pod_sc = pod_spec.security_context
        assert pod_sc.seccomp_profile.type == "RuntimeDefault"
        assert pod_sc.fs_group == 1000

        # Same shared writable surface as GCP: the provisioner image is identical
        # cross-cloud, so both adapters build from the one cloud-neutral contract.
        assert {v.name for v in pod_spec.volumes} == {
            "provisioner-workspace",
            "tmp",
            "tf-plugin-cache",
            "pulumi-home",
        }

    def test_requires_namespace(self) -> None:
        runner = AWSKubernetesTaskRunner()
        with pytest.raises(CloudTaskError, match="namespace"):
            runner.run_task(
                task_definition="image:latest",
                cluster="",
                command=["range", "provision"],
                container_name=PROVISIONER_CONTAINER_NAME,
            )


class TestAWSTaskRunnerSelection:
    def test_get_task_runner_returns_aws_kubernetes_runner(self, settings) -> None:
        from shared.cloud import get_task_runner

        settings.CLOUD_PROVIDER = "aws"
        assert isinstance(get_task_runner(), AWSKubernetesTaskRunner)
