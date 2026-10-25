"""A matching label or success counter cannot substitute for worker ownership."""

from io import BytesIO
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest

from shared.cloud.exceptions import CloudTaskError
from shared.cloud.kubernetes._output import MAX_TASK_OUTPUT_BYTES, read_task_output


@pytest.fixture
def invocation():
    expected = {
        "task_identity": "invocation",
        "service_account_name": "plugin-worker",
        "container_name": "plugin",
        "image": "example.test/worker@sha256:" + "a" * 64,
        "command": [],
    }
    container = NS(name="plugin", image=expected["image"], args=[])
    spec = NS(containers=[container], service_account_name="plugin-worker")
    job = NS(
        metadata=NS(name="job", uid="job-uid", annotations={"shifter.dev/task-identity": "invocation"}),
        spec=NS(template=NS(spec=spec)),
        status=NS(succeeded=1, failed=0),
    )
    owner = NS(uid="job-uid", kind="Job", name="job", controller=True)
    pod = NS(
        metadata=NS(name="pod", uid="pod-uid", owner_references=[owner]),
        spec=spec,
        status=NS(
            phase="Succeeded",
            container_statuses=[
                NS(name="plugin", restart_count=0, state=NS(terminated=NS(exit_code=0))),
            ],
        ),
    )
    response = Mock()
    response.read.return_value = b'{"status":"compatible"}'
    batch = Mock()
    batch.read_namespaced_job.return_value = job
    core = Mock()
    core.list_namespaced_pod.return_value = NS(items=[pod])
    core.read_namespaced_pod_log.return_value = response
    return NS(batch=batch, core=core, expected=expected, job=job, pod=pod, response=response)


def read(item, task="plugins/job"):
    return read_task_output(item.batch, item.core, "plugins", task, item.expected)


def test_reads_start_of_bounded_stream_and_releases_connection(invocation):
    assert read(invocation) == b'{"status":"compatible"}'
    invocation.response.read.assert_called_once_with(MAX_TASK_OUTPUT_BYTES + 1, decode_content=True)
    invocation.response.close.assert_called_once()
    invocation.response.release_conn.assert_called_once()
    kwargs = invocation.core.read_namespaced_pod_log.call_args.kwargs
    assert kwargs["_preload_content"] is False
    assert "limit_bytes" not in kwargs
    assert "tail_lines" not in kwargs


@pytest.mark.parametrize("change", ["namespace", "image", "owner", "container", "restart", "exit", "ambiguous"])
def test_identity_and_ownership_fail_before_log_read(invocation, change):
    task = "plugins/job"
    if change == "namespace":
        task = "other/job"
    elif change == "image":
        invocation.job.spec.template.spec.containers[0].image = "wrong-image"
    elif change == "owner":
        invocation.pod.metadata.owner_references[0].uid = "different-job"
    elif change == "container":
        invocation.pod.status.container_statuses[0].name = "sidecar"
    elif change == "restart":
        invocation.pod.status.container_statuses[0].restart_count = 1
    elif change == "exit":
        invocation.pod.status.container_statuses[0].state.terminated.exit_code = 1
    else:
        invocation.core.list_namespaced_pod.return_value.items.append(invocation.pod)
    with pytest.raises(CloudTaskError):
        read(invocation, task)
    invocation.core.read_namespaced_pod_log.assert_not_called()


def test_pending_job_has_no_result(invocation):
    invocation.job.status.succeeded = 0
    assert read(invocation) is None
    invocation.core.read_namespaced_pod_log.assert_not_called()


def test_oversized_prefix_cannot_be_dropped_to_accept_valid_suffix(invocation):
    stream = BytesIO(b"x" * MAX_TASK_OUTPUT_BYTES + b'{"status":"compatible"}')
    invocation.response.read.side_effect = lambda size, **kwargs: stream.read(size)
    with pytest.raises(CloudTaskError, match="bound"):
        read(invocation)
    assert stream.tell() == MAX_TASK_OUTPUT_BYTES + 1
    invocation.response.close.assert_called_once()


def test_stream_failure_still_closes_connection(invocation):
    invocation.response.read.side_effect = TimeoutError()
    with pytest.raises(TimeoutError):
        read(invocation)
    invocation.response.close.assert_called_once()
    invocation.response.release_conn.assert_called_once()
