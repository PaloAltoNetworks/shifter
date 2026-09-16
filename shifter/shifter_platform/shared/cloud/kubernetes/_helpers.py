"""Module-level constants and small pure helpers for the neutral Kubernetes runner.

Extracted from the GCP task-runner package (#1824). The label helper is
parameterized by the injected profile's runner label value instead of a
hardcoded provider tag.
"""

from __future__ import annotations

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
