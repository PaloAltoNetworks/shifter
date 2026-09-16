"""Contract tests for GCPTaskRunner.interrupt_task (#277).

The interrupt seam verifies the observed Job is exactly the reserved provisioner
intent before deleting it (foreground propagation), then reports an idempotent
task-control disposition -- never range lifecycle success. Only the Kubernetes
client boundary is mocked; the verification/deletion/observation logic is real.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from shared.cloud.exceptions import CloudTaskError
from shared.cloud.gcp.task_runner import GCPTaskRunner
from shared.cloud.kubernetes.naming import build_idempotent_job_name
from shared.cloud.types import TaskInterruptDisposition
from tests.shared.cloud.test_gcp_task_runner import _ApiException, _make_fake_k8s_client, _observed_job

_TASK_IDENTITY = "11111111-1111-1111-1111-111111111111"
_NAMESPACE = "shifter-platform"
_IMAGE = "provisioner:latest"
_SA = "shifter-provisioner"
_COMMAND = ["raes-range", "provision", "--request-id", "22222222-2222-2222-2222-222222222222"]


def _job_name() -> str:
    return build_idempotent_job_name("pulumi-provisioner", _TASK_IDENTITY)


def _task_ref() -> str:
    return f"{_NAMESPACE}/{_job_name()}"


def _expected_identity() -> dict:
    return {
        "task_identity": _TASK_IDENTITY,
        "image": _IMAGE,
        "command": _COMMAND,
        "container_name": "pulumi-provisioner",
        "service_account_name": _SA,
        "secret_name": None,
    }


def _pods(count: int) -> SimpleNamespace:
    return SimpleNamespace(items=[SimpleNamespace() for _ in range(count)])


def _wire(runner, *, read_result=None, read_raises=None, pods=0):
    batch_api = MagicMock()
    core_api = MagicMock()
    client = _make_fake_k8s_client()
    client.V1DeleteOptions = lambda **kwargs: SimpleNamespace(**kwargs)
    if read_raises is not None:
        batch_api.read_namespaced_job.side_effect = read_raises
    else:
        batch_api.read_namespaced_job.return_value = read_result
    core_api.list_namespaced_pod.return_value = _pods(pods)
    runner._load_kubernetes_api = MagicMock(return_value=(batch_api, core_api, client, _ApiException))
    return batch_api, core_api


class TestGCPTaskRunnerInterrupt:
    def test_matching_job_deleted_foreground_and_terminal_absent(self):
        runner = GCPTaskRunner()
        observed = _observed_job(task_identity=_TASK_IDENTITY, image=_IMAGE, command=_COMMAND, service_account_name=_SA)
        batch_api, _core = _wire(runner, read_result=observed, pods=0)

        disposition = runner.interrupt_task(_NAMESPACE, _task_ref(), _expected_identity())

        assert disposition == TaskInterruptDisposition.TERMINAL_ABSENT
        assert batch_api.delete_namespaced_job.call_count == 1
        kwargs = batch_api.delete_namespaced_job.call_args.kwargs
        assert kwargs["name"] == _job_name()
        assert kwargs["namespace"] == _NAMESPACE
        assert kwargs["body"].propagation_policy == "Foreground"

    def test_matching_job_pods_remain_reports_stopping(self):
        runner = GCPTaskRunner()
        observed = _observed_job(task_identity=_TASK_IDENTITY, image=_IMAGE, command=_COMMAND, service_account_name=_SA)
        batch_api, _core = _wire(runner, read_result=observed, pods=1)

        disposition = runner.interrupt_task(_NAMESPACE, _task_ref(), _expected_identity())

        assert disposition == TaskInterruptDisposition.STOPPING
        assert batch_api.delete_namespaced_job.call_count == 1

    def test_identity_mismatch_fails_closed_without_delete(self):
        runner = GCPTaskRunner()
        # Same reserved name, different image -> not this intent.
        observed = _observed_job(
            task_identity=_TASK_IDENTITY, image="attacker:evil", command=_COMMAND, service_account_name=_SA
        )
        batch_api, _core = _wire(runner, read_result=observed, pods=1)

        disposition = runner.interrupt_task(_NAMESPACE, _task_ref(), _expected_identity())

        assert disposition == TaskInterruptDisposition.IDENTITY_MISMATCH
        batch_api.delete_namespaced_job.assert_not_called()

    def test_absent_job_pods_gone_is_terminal_absent(self):
        runner = GCPTaskRunner()
        batch_api, _core = _wire(runner, read_raises=_ApiException(404), pods=0)

        disposition = runner.interrupt_task(_NAMESPACE, _task_ref(), _expected_identity())

        assert disposition == TaskInterruptDisposition.TERMINAL_ABSENT
        batch_api.delete_namespaced_job.assert_not_called()

    def test_absent_job_pods_remain_is_unknown(self):
        runner = GCPTaskRunner()
        batch_api, _core = _wire(runner, read_raises=_ApiException(404), pods=2)

        disposition = runner.interrupt_task(_NAMESPACE, _task_ref(), _expected_identity())

        assert disposition == TaskInterruptDisposition.UNKNOWN
        batch_api.delete_namespaced_job.assert_not_called()

    def test_missing_task_ref_raises(self):
        runner = GCPTaskRunner()
        identity = _expected_identity()
        with pytest.raises(CloudTaskError):
            runner.interrupt_task(_NAMESPACE, "", identity)
