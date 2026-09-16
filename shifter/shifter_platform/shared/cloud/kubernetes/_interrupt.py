"""Interrupt (stop) a deterministic task Job (#277).

The launcher worker calls this to actively terminate an in-flight task after a
cancellation. It verifies the observed Job is exactly the reserved intent before
any mutation, deletes it with **foreground propagation** so the workload's pods
are torn down before the task is treated as absent, and returns an idempotent
``TaskInterruptDisposition`` -- never range lifecycle success.

Identity is verified on the six deterministic fields the launcher stamps
(``job_name`` derived from ``task_identity``, the task-identity annotation, image,
container args, container name, and service account). The per-Job Secret binding
is intentionally not re-verified here: it is conditional on sensitive env, and the
provider's admission policy already guarantees the canonical binding for any Job
that could match this name.

Extracted from the GCP task-runner package (#1824).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

from shared.cloud.exceptions import CloudTaskError
from shared.cloud.types import TaskInterruptDisposition

from ._helpers import _KUBERNETES_REQUEST_TIMEOUT_SECONDS, _SHIFTER_ANNOTATION_TASK_IDENTITY, _api_call
from ._job_lifecycle import _read_idempotent_job
from .naming import parse_job_task_id

if TYPE_CHECKING:
    from types import ModuleType

    from ._runner import KubernetesTaskRunner

logger = logging.getLogger(__name__)


def _observed_identity(job: object) -> dict[str, Any]:
    """Project the observed Job onto its deterministic identity fields."""
    metadata = getattr(job, "metadata", None)
    annotations = getattr(metadata, "annotations", None) or {}
    pod_spec = getattr(getattr(getattr(job, "spec", None), "template", None), "spec", None)
    containers = getattr(pod_spec, "containers", None) or []
    container = containers[0] if len(containers) == 1 else None
    return {
        "job_name": getattr(metadata, "name", None),
        "task_identity": annotations.get(_SHIFTER_ANNOTATION_TASK_IDENTITY),
        "service_account_name": getattr(pod_spec, "service_account_name", None) or "",
        "container_name": getattr(container, "name", None),
        "image": getattr(container, "image", None),
        "command": list(getattr(container, "args", None) or []),
    }


def _is_reserved_intent(job: object, job_name: str, expected: dict[str, Any]) -> bool:
    """Return True only when the observed Job is exactly this reserved intent."""
    return _observed_identity(job) == {
        "job_name": job_name,
        "task_identity": str(expected["task_identity"]),
        "service_account_name": str(expected["service_account_name"]),
        "container_name": str(expected["container_name"]),
        "image": str(expected["image"]),
        "command": list(expected["command"]),
    }


def _pods_gone(core_api: object, namespace: str, job_name: str, api_exception: type[Exception]) -> bool:
    """Return True when no pods remain for the Job (foreground deletion complete).

    A Job ``404`` alone is not sufficient after a background delete; the workload
    is only absent once its pods are gone.
    """
    try:
        pods = _api_call(
            core_api,
            "list_namespaced_pod",
            namespace=namespace,
            label_selector=f"job-name={job_name}",
            _request_timeout=_KUBERNETES_REQUEST_TIMEOUT_SECONDS,
        )
    except api_exception as exc:
        if getattr(exc, "status", None) == 404:
            return True
        raise
    return not list(getattr(pods, "items", None) or [])


def _deleting(job: object) -> bool:
    """Return True when the Job already carries a deletion timestamp (interrupt in flight)."""
    return getattr(getattr(job, "metadata", None), "deletion_timestamp", None) is not None


def _absent_or(
    core_api: object,
    namespace: str,
    job_name: str,
    api_exception: type[Exception],
    otherwise: str,
) -> str:
    """``TERMINAL_ABSENT`` once the Job's pods are gone, else ``otherwise``.

    The workload is only terminally absent once its pods are gone, so this is the
    single place that maps pod presence to the caller's non-terminal disposition.
    """
    if _pods_gone(core_api, namespace, job_name, api_exception):
        return TaskInterruptDisposition.TERMINAL_ABSENT
    return otherwise


def interrupt_job(runner: KubernetesTaskRunner, cluster: str, task_ref: str, expected_identity: dict[str, Any]) -> str:
    """Verify identity and stop the reserved task Job. Returns a disposition."""
    namespace, job_name = parse_job_task_id(task_ref, cluster) if task_ref else ("", "")
    if not namespace or not job_name:
        raise CloudTaskError("Kubernetes interrupt requires a namespace/job task reference")

    batch_api, core_api, client, api_exception = runner._load_kubernetes_api()
    # The loader hands back the dynamically imported ``kubernetes.client`` module.
    client_lib = cast("ModuleType", client)

    job = _read_idempotent_job(batch_api, api_exception, namespace, job_name)
    if job is None:
        # Job object already gone; the workload is absent only once its pods are.
        return _absent_or(core_api, namespace, job_name, api_exception, TaskInterruptDisposition.UNKNOWN)

    # Never mutate a workload that is not this exact reserved intent (fail closed).
    if not _is_reserved_intent(job, job_name, expected_identity):
        logger.warning("interrupt_task: identity mismatch job=%s namespace=%s", job_name, namespace)
        return TaskInterruptDisposition.IDENTITY_MISMATCH

    # Issue the foreground delete unless an interrupt is already in flight; either
    # way converge on terminal absence once the pods are gone.
    if not _deleting(job):
        _api_call(
            batch_api,
            "delete_namespaced_job",
            name=job_name,
            namespace=namespace,
            body=client_lib.V1DeleteOptions(propagation_policy="Foreground"),
            _request_timeout=_KUBERNETES_REQUEST_TIMEOUT_SECONDS,
        )

    return _absent_or(core_api, namespace, job_name, api_exception, TaskInterruptDisposition.STOPPING)
