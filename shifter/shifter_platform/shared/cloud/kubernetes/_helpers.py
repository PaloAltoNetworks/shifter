"""Module-level constants and small pure helpers for the neutral Kubernetes runner.

Extracted from the GCP task-runner package (#1824). The label helper is
parameterized by the injected profile's runner label value instead of a
hardcoded provider tag.
"""

from __future__ import annotations

import json
import secrets
import time
from collections.abc import Callable

# Canonical Kubernetes recommended labels referenced by multiple
# spec builders (Job metadata, Pod template, Secret metadata).
_K8S_LABEL_PART_OF = "app.kubernetes.io/part-of"
_K8S_LABEL_COMPONENT = "app.kubernetes.io/component"
_SHIFTER_PART_OF_VALUE = "shifter"
_SHIFTER_LABEL_TASK_RUNNER = "shifter.dev/task-runner"
_SHIFTER_ANNOTATION_TASK_IDENTITY = "shifter.dev/task-identity"
_KUBERNETES_REQUEST_TIMEOUT_SECONDS = 30

# Naming convention minted by ``_build_secret_name`` (``<prefix>-secrets-<suffix>``).
# The reconcile paths detect the per-Job sensitive-env Secret referenced by an
# observed Job through this neutral infix rather than any provider-specific prefix.
# (This is a DNS-1123 fragment of the Kubernetes Secret *object* name, not a
# credential; the identifier deliberately avoids a "secret"/"password" token so
# the bandit hardcoded-password heuristic does not false-positive on it.)
_SENSITIVE_ENV_NAME_INFIX = "-secrets-"


def _api_call(api: object, method: str, **kwargs: object) -> object:
    """Invoke one method on a dynamically loaded Kubernetes client object."""
    callback = getattr(api, method)
    return callback(**kwargs)


# Bounded retry for admission conflicts: full-jitter exponential backoff (caps
# 0.1, 0.2, 0.4, 0.8, 1.6s) so writers racing on one ResourceQuota desynchronize.
ADMISSION_CONFLICT_ATTEMPTS = 6
_ADMISSION_CONFLICT_BASE_SECONDS = 0.1
_jitter = secrets.SystemRandom()


def _status_reason(exc: object) -> str:
    """Return the Kubernetes ``Status.reason`` carried in an API exception body, or ``""``."""
    body = getattr(exc, "body", None)
    if isinstance(body, bytes):
        body = body.decode("utf-8", "replace")
    if not isinstance(body, str) or not body:
        return ""
    try:
        payload = json.loads(body)
    except ValueError:
        return ""
    reason = payload.get("reason") if isinstance(payload, dict) else None
    return reason if isinstance(reason, str) else ""


def is_admission_conflict(exc: object) -> bool:
    """Return whether a 409 rejected the write rather than reporting an existing object.

    The API server answers HTTP 409 both for ``AlreadyExists`` and for a write it
    refused on an optimistic-concurrency ``Conflict`` -- notably ResourceQuota
    admission when several objects are created in one namespace at once. Only
    the Status ``reason`` tells them apart; after a ``Conflict`` nothing was
    created, so treating it as "already exists" acts on an object that is absent.
    """
    return getattr(exc, "status", None) == 409 and _status_reason(exc) == "Conflict"


def admission_conflict_backoff_seconds(attempt: int) -> float:
    """Return the jittered delay before retry ``attempt + 1`` of a conflicted write."""
    return _jitter.uniform(0, _ADMISSION_CONFLICT_BASE_SECONDS * (2**attempt))


def create_with_admission_retry[T](create: Callable[[], T]) -> T:
    """Run a create call, retrying admission conflicts with bounded jittered backoff."""
    for attempt in range(ADMISSION_CONFLICT_ATTEMPTS - 1):
        try:
            return create()
        except Exception as exc:
            if not is_admission_conflict(exc):
                raise
            time.sleep(admission_conflict_backoff_seconds(attempt))
    # Final attempt: any error, including a still-conflicting write, propagates.
    return create()


def _shifter_resource_labels(
    container_name: str,
    *,
    include_task_runner: bool,
    runner_label_value: str,
) -> dict[str, str]:
    """Build the standard Shifter label set for K8s resources.

    The label set varies between Pod-template labels (no task-runner
    tag) and Job/Secret metadata (with task-runner tag). Container
    names are truncated to 63 characters to stay within the
    Kubernetes label-value length limit. ``runner_label_value`` is the
    provider tag supplied by the injected task profile.
    """
    labels = {
        _K8S_LABEL_PART_OF: _SHIFTER_PART_OF_VALUE,
        _K8S_LABEL_COMPONENT: container_name[:63],
    }
    if include_task_runner:
        labels[_SHIFTER_LABEL_TASK_RUNNER] = runner_label_value
    return labels


def _job_condition_reason(status: object) -> str | None:
    """Return the message/reason of the first Failed/Complete Job condition, if any."""
    for condition in getattr(status, "conditions", None) or []:
        if getattr(condition, "type", "") in {"Failed", "Complete"}:
            return getattr(condition, "message", None) or getattr(condition, "reason", None)
    return None


def _derive_job_state(*, active: int, failed: int, succeeded: int) -> str:
    """Map active/failed/succeeded Job counts to a coarse ECS-style task state."""
    if succeeded > 0:
        return "SUCCEEDED"
    if failed > 0:
        return "FAILED"
    return "RUNNING" if active > 0 else "SUBMITTED"
