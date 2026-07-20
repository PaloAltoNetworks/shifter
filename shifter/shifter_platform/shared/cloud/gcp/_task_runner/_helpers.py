"""Module-level constants and small pure helpers for the GCP task runner.

Split out of the historical monolithic ``task_runner.py`` (#561) so the
constants and stateless helpers used by more than one launch/observe/status
submodule live in one place instead of being duplicated.
"""

from __future__ import annotations

from shared.cloud import PROVISIONER_CONTAINER_NAME

_PROVISIONER_RUN_AS_UID = 1000
_PROVISIONER_RUN_AS_GID = 1000

# Canonical Kubernetes recommended labels referenced by multiple
# spec builders (Job metadata, Pod template, Secret metadata).
_K8S_LABEL_PART_OF = "app.kubernetes.io/part-of"
_K8S_LABEL_COMPONENT = "app.kubernetes.io/component"
_SHIFTER_PART_OF_VALUE = "shifter"
_SHIFTER_LABEL_TASK_RUNNER = "shifter.dev/task-runner"
_SHIFTER_TASK_RUNNER_GCP = "gcp"
_SHIFTER_ANNOTATION_TASK_IDENTITY = "shifter.dev/task-identity"
_KUBERNETES_REQUEST_TIMEOUT_SECONDS = 30

# Memory-backed workspace volume size cap. Terraform staging trees are tiny
# (a few MB), but a runaway plan log or provider download could otherwise
# consume node memory unbounded. 256Mi is generous for the staged terraform/
# tree plus typical plan output without putting the node under pressure.
_PROVISIONER_WORKSPACE_SIZE_LIMIT = "256Mi"

# Writable mount points the provisioner image needs at runtime. /app and the
# rest of the root filesystem are read-only (issue #1103); these explicit
# emptyDir volumes are the only paths the runtime user can write to.
# - workspace: terraform_base._stage_workspace target. Memory-backed (medium=Memory)
#   so terraform.tfvars.json (which can carry secrets) does not persist on disk;
#   capped at _PROVISIONER_WORKSPACE_SIZE_LIMIT to bound the worst-case node memory
#   pressure from a runaway plan log or large provider download.
# - /tmp: Python tempfile, kubectl temp kubeconfigs (gdc_*), etc.
# - tf plugin cache and pulumi home: Terraform/Pulumi tool state under HOME.
_PROVISIONER_WRITABLE_MOUNTS: tuple[tuple[str, str, str | None, str | None], ...] = (
    ("provisioner-workspace", "/var/run/provisioner/workspace", "Memory", _PROVISIONER_WORKSPACE_SIZE_LIMIT),
    ("tmp", "/tmp", None, None),  # noqa: S108 # nosec B108 — Kubernetes mount path, not a tempfile API call
    ("tf-plugin-cache", "/home/appuser/.terraform.d/plugin-cache", None, None),
    ("pulumi-home", "/home/appuser/.pulumi", None, None),
)


def _api_call(api: object, method: str, **kwargs: object) -> object:
    """Invoke one method on a dynamically loaded Kubernetes client object."""
    callback = getattr(api, method)
    return callback(**kwargs)


def _shifter_resource_labels(container_name: str, *, include_task_runner: bool) -> dict[str, str]:
    """Build the standard Shifter label set for K8s resources.

    The label set varies between Pod-template labels (no task-runner
    tag) and Job/Secret metadata (with task-runner tag). Container
    names are truncated to 63 characters to stay within the
    Kubernetes label-value length limit.
    """
    labels = {
        _K8S_LABEL_PART_OF: _SHIFTER_PART_OF_VALUE,
        _K8S_LABEL_COMPONENT: container_name[:63],
    }
    if include_task_runner:
        labels[_SHIFTER_LABEL_TASK_RUNNER] = _SHIFTER_TASK_RUNNER_GCP
    return labels


def _is_provisioner_task(container_name: str) -> bool:
    """Return True if the Job being built is the provisioner task.

    Hardening from issue #1103 (read-only root filesystem, writable workspace
    volume, drop-ALL capabilities, etc.) is provisioner-specific. CMS
    experiments and any future shared-runner caller keep their current,
    less-prescribed contract until the runner protocol grows a per-task
    runtime profile parameter.
    """
    return container_name == PROVISIONER_CONTAINER_NAME


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
