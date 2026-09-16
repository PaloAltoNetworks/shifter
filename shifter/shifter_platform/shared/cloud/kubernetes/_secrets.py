"""Secret + ownership lifecycle for the ephemeral per-Job sensitive-env Secret.

Extracted from the GCP task-runner package (#1824). Handles naming,
creating/recovering the Secret, wiring an owner reference to the Job that
consumes it, and unwinding both objects when a launch fails partway through.
The mechanism is generic Kubernetes; the runner label value arrives via the
injected profile.
"""

from __future__ import annotations

import logging
import uuid
from hashlib import sha256
from typing import cast

from shared.cloud.exceptions import CloudTaskError
from shared.log_sanitize import safe_log_fingerprint

from ._helpers import _KUBERNETES_REQUEST_TIMEOUT_SECONDS, _api_call
from ._job_manifest import _build_sensitive_secret
from ._types import _KubernetesApis, _OwnerReference

logger = logging.getLogger(__name__)


def _build_secret_name(container_name: str, task_identity: str | None = None) -> str:
    """Derive a unique Secret name for a task Job.

    Kubernetes object names cap at 253 characters and follow DNS
    subdomain rules. We keep the prefix under 50 characters and
    append either a stable 16-character digest of the launch intent
    or, for legacy callers, a fresh 12-character UUID slice.
    """
    # Lowercase + replace any non-DNS-subdomain characters.
    prefix = container_name.lower().replace("_", "-")
    # Trim to a generous bound; the runtime contract is just "unique".
    prefix = prefix[:40].rstrip("-") or "provisioner"
    suffix = sha256(task_identity.encode("utf-8")).hexdigest()[:16] if task_identity else uuid.uuid4().hex[:12]
    return f"{prefix}-secrets-{suffix}"


def _ensure_sensitive_secret(
    *,
    apis: _KubernetesApis,
    namespace: str,
    secret_name: str,
    sensitive_env: dict[str, str],
    container_name: str,
    task_identity: str | None,
    runner_label_value: str,
) -> None:
    """Create a per-intent Secret, or recover it after an ambiguous create."""
    secret_body = _build_sensitive_secret(apis.client, secret_name, sensitive_env, container_name, runner_label_value)
    try:
        _api_call(
            apis.core,
            "create_namespaced_secret",
            namespace=namespace,
            body=secret_body,
            _request_timeout=_KUBERNETES_REQUEST_TIMEOUT_SECONDS,
        )
    except apis.exception as exc:
        if task_identity is None or getattr(exc, "status", None) != 409:
            raise
        # A deterministic per-intent Secret can remain after an ambiguous
        # create response. Reassert its exact payload/labels and remove any
        # stale owner before attaching it to the newly accepted Job.
        patch_body = {
            "metadata": {
                "labels": getattr(getattr(secret_body, "metadata", None), "labels", None) or {},
                "ownerReferences": [],
            },
            "stringData": dict(sensitive_env),
            "type": "Opaque",
        }
        _api_call(
            apis.core,
            "patch_namespaced_secret",
            name=secret_name,
            namespace=namespace,
            body=patch_body,
            _request_timeout=_KUBERNETES_REQUEST_TIMEOUT_SECONDS,
        )


def _owner_ref_to_dict(owner_ref: _OwnerReference) -> dict[str, object]:
    """Convert a V1OwnerReference to the camelCase dict shape the
    apiserver expects in a strategic-merge patch body."""
    return {
        "apiVersion": owner_ref.api_version,
        "kind": owner_ref.kind,
        "name": owner_ref.name,
        "uid": owner_ref.uid,
        "controller": owner_ref.controller,
        "blockOwnerDeletion": owner_ref.block_owner_deletion,
    }


def _cleanup_sensitive_secret(core_api: object, secret_name: str | None, namespace: str) -> None:
    """Delete an orphan sensitive-env Secret. Best-effort: log on
    failure so the operator can clean up manually, but never raise
    — the caller is already on an error path."""
    if not secret_name:
        return
    try:
        _api_call(
            core_api,
            "delete_namespaced_secret",
            name=secret_name,
            namespace=namespace,
            _request_timeout=_KUBERNETES_REQUEST_TIMEOUT_SECONDS,
        )
    except Exception:
        logger.warning(
            "run_task: failed to clean up orphan secret_fp=%s namespace=%s",
            safe_log_fingerprint(secret_name),
            namespace,
            exc_info=True,
        )


def _install_owner_reference_or_unwind(
    *,
    apis: _KubernetesApis,
    namespace: str,
    job_name: str,
    job_uid: str | None,
    secret_name: str,
    unwind_on_failure: bool = True,
) -> None:
    """Patch the Secret's ownerReferences. If the patch fails (or
    the Job uid was unavailable), delete BOTH the Job and the
    Secret and raise CloudTaskError — the alternative is an
    indefinite orphan Secret with sensitive payload."""
    if not job_uid:
        if unwind_on_failure:
            _unwind_run(
                apis.batch,
                apis.core,
                namespace,
                job_name,
                secret_name,
                detail="created Job lacks a uid we can use as ownerReference target",
            )
        raise CloudTaskError(
            f"Kubernetes task runner: cannot install Secret ownerReference (Job {job_name} returned no uid)"
        )

    owner_ref = cast(
        _OwnerReference,
        _api_call(
            apis.client,
            "V1OwnerReference",
            api_version="batch/v1",
            kind="Job",
            name=job_name,
            uid=job_uid,
            controller=True,
            block_owner_deletion=True,
        ),
    )
    patch_body = {"metadata": {"ownerReferences": [_owner_ref_to_dict(owner_ref)]}}
    try:
        _api_call(
            apis.core,
            "patch_namespaced_secret",
            name=secret_name,
            namespace=namespace,
            body=patch_body,
            _request_timeout=_KUBERNETES_REQUEST_TIMEOUT_SECONDS,
        )
    except Exception as patch_err:
        if unwind_on_failure:
            _unwind_run(
                apis.batch,
                apis.core,
                namespace,
                job_name,
                secret_name,
                detail=f"ownerReference patch failed ({type(patch_err).__name__})",
            )
        raise CloudTaskError(
            f"Kubernetes task runner: failed to install Secret ownerReference for Job {job_name} "
            f"({type(patch_err).__name__})"
        ) from patch_err


def _unwind_run(
    batch_api: object,
    core_api: object,
    namespace: str,
    job_name: str,
    secret_name: str,
    *,
    detail: str,
) -> None:
    """Delete the Job and the Secret we created earlier in this
    run. Each delete is best-effort: we log and continue so the
    caller's exception (raised after we return) carries the
    original cause."""
    logger.warning(
        "run_task: unwinding run for job=%s secret_fp=%s namespace=%s reason=%s",
        job_name,
        safe_log_fingerprint(secret_name),
        namespace,
        detail,
    )
    try:
        _api_call(
            batch_api,
            "delete_namespaced_job",
            name=job_name,
            namespace=namespace,
            _request_timeout=_KUBERNETES_REQUEST_TIMEOUT_SECONDS,
        )
    except Exception:
        logger.warning(
            "run_task: failed to delete Job during unwind job=%s namespace=%s",
            job_name,
            namespace,
            exc_info=True,
        )
    try:
        _api_call(
            core_api,
            "delete_namespaced_secret",
            name=secret_name,
            namespace=namespace,
            _request_timeout=_KUBERNETES_REQUEST_TIMEOUT_SECONDS,
        )
    except Exception:
        logger.warning(
            "run_task: failed to delete Secret during unwind secret_fp=%s namespace=%s",
            safe_log_fingerprint(secret_name),
            namespace,
            exc_info=True,
        )
