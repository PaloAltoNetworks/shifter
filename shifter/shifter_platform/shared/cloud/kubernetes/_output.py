"""Read bounded output from one completed, identity-checked task invocation."""

from __future__ import annotations

from typing import Any, Protocol, cast

from shared.cloud.exceptions import CloudTaskError

from ._helpers import _KUBERNETES_REQUEST_TIMEOUT_SECONDS, _api_call
from ._interrupt import _is_reserved_intent
from .naming import parse_job_task_id

MAX_TASK_OUTPUT_BYTES = 1_048_576


class _LogResponse(Protocol):
    """Streaming response ownership needed to bound and release pod logs."""

    def read(self, amt: int, *, decode_content: bool) -> bytes: ...
    def close(self) -> None: ...
    def release_conn(self) -> None: ...


def _validate_completed_container(pod: object, expected: dict[str, Any]) -> None:
    """Require the exact container invocation to have exited successfully without retries."""
    spec = getattr(pod, "spec", None)
    containers = getattr(spec, "containers", None) or []
    if (
        len(containers) != 1
        or getattr(containers[0], "name", None) != expected["container_name"]
        or getattr(containers[0], "image", None) != expected["image"]
        or list(getattr(containers[0], "args", None) or []) != expected["command"]
        or getattr(spec, "service_account_name", None) != expected["service_account_name"]
    ):
        raise CloudTaskError("Task output container mismatch")
    _validate_container_exit(pod, expected["container_name"])


def _validate_container_exit(pod: object, container_name: str) -> None:
    """Accept only a successful container exit with no restarted attempts."""
    pod_status = getattr(pod, "status", None)
    statuses = getattr(pod_status, "container_statuses", None) or []
    if (
        getattr(pod_status, "phase", None) != "Succeeded"
        or len(statuses) != 1
        or getattr(statuses[0], "name", None) != container_name
        or getattr(statuses[0], "restart_count", None) != 0
        or getattr(getattr(getattr(statuses[0], "state", None), "terminated", None), "exit_code", None) != 0
    ):
        raise CloudTaskError("Task output completion is unavailable")


def _completed_pod_name(
    core_api: object,
    job: object,
    namespace: str,
    job_name: str,
    expected: dict[str, Any],
) -> str:
    """Select the sole completed pod controlled by the verified Job UID."""
    job_uid = getattr(getattr(job, "metadata", None), "uid", None)
    listed = _api_call(
        core_api,
        "list_namespaced_pod",
        namespace=namespace,
        label_selector=f"job-name={job_name}",
        _request_timeout=_KUBERNETES_REQUEST_TIMEOUT_SECONDS,
    )
    pods = list(getattr(listed, "items", None) or [])
    if not job_uid or len(pods) != 1:
        raise CloudTaskError("Task output ownership is unavailable")
    pod = pods[0]
    metadata = getattr(pod, "metadata", None)
    _validate_job_controller(metadata, job_uid, job_name)
    _validate_completed_container(pod, expected)
    pod_name = getattr(metadata, "name", None)
    if not isinstance(pod_name, str) or not pod_name:
        raise CloudTaskError("Task output pod identity is unavailable")
    return pod_name


def _validate_job_controller(metadata: object, job_uid: str, job_name: str) -> None:
    """Require the exact Job UID as the pod's sole controlling owner."""
    owners = getattr(metadata, "owner_references", None) or []
    controllers = [owner for owner in owners if getattr(owner, "controller", False)]
    if len(controllers) != 1 or (
        getattr(controllers[0], "uid", None) != job_uid
        or getattr(controllers[0], "kind", None) != "Job"
        or getattr(controllers[0], "name", None) != job_name
    ):
        raise CloudTaskError("Task output ownership mismatch")


def read_task_output(
    batch_api: object,
    core_api: object,
    namespace: str,
    task_ref: str,
    expected: dict[str, Any],
) -> bytes | None:
    """Return output only for the exact finished Job and its sole owned Pod.

    A label match is not ownership. A successful Job with missing or ambiguous
    pod evidence cannot supply a result. Streaming starts at the beginning and
    reads at most the bound plus one byte, so a valid JSON suffix of oversized
    logs cannot be mistaken for the complete response.
    """
    observed_namespace, job_name = parse_job_task_id(task_ref, namespace)
    if observed_namespace != namespace or not job_name:
        raise CloudTaskError("Task output identity mismatch")
    job = _api_call(
        batch_api,
        "read_namespaced_job",
        name=job_name,
        namespace=namespace,
        _request_timeout=_KUBERNETES_REQUEST_TIMEOUT_SECONDS,
    )
    if not _is_reserved_intent(job, job_name, expected):
        raise CloudTaskError("Task output identity mismatch")
    status = getattr(job, "status", None)
    if getattr(status, "failed", 0):
        raise CloudTaskError("Task execution failed")
    if not getattr(status, "succeeded", 0):
        return None
    pod_name = _completed_pod_name(core_api, job, namespace, job_name, expected)
    response = _api_call(
        core_api,
        "read_namespaced_pod_log",
        name=pod_name,
        namespace=namespace,
        container=expected["container_name"],
        follow=False,
        previous=False,
        timestamps=False,
        _preload_content=False,
        _request_timeout=_KUBERNETES_REQUEST_TIMEOUT_SECONDS,
    )
    stream = cast(_LogResponse, response)
    try:
        raw = stream.read(MAX_TASK_OUTPUT_BYTES + 1, decode_content=True)
    finally:
        stream.close()
        stream.release_conn()
    if not isinstance(raw, bytes) or len(raw) > MAX_TASK_OUTPUT_BYTES:
        raise CloudTaskError("Task output exceeds its bound")
    return raw
