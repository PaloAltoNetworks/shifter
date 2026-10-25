"""Observe/validate/create-or-observe logic for deterministic task Jobs.

Extracted from the GCP task-runner package (#1824). This module owns the "did we
already accept this exact Job" reconciliation path used by both the idempotent
pre-check in ``_run_task_flow._existing_task_ref`` and the ambiguous-create
recovery in ``_create_or_observe_job``.
"""

from __future__ import annotations

import time

from shared.cloud.exceptions import CloudTaskError

from ._helpers import (
    _KUBERNETES_REQUEST_TIMEOUT_SECONDS,
    _SENSITIVE_ENV_NAME_INFIX,
    _SHIFTER_ANNOTATION_TASK_IDENTITY,
    ADMISSION_CONFLICT_ATTEMPTS,
    _api_call,
    admission_conflict_backoff_seconds,
)
from ._secrets import _cleanup_sensitive_secret, _install_owner_reference_or_unwind
from ._types import _JobIdentity, _JobLaunch, _KubernetesApis


def _job_sensitive_secret_name(job: object) -> str | None:
    """Return the per-Job sensitive-env Secret referenced by a Job.

    Detection keys on the neutral Secret-name convention minted by
    ``_build_secret_name`` (``<prefix>-secrets-<suffix>``) rather than a
    provider-specific prefix, so the reconcile path stays cloud-neutral.
    """
    pod_spec = getattr(getattr(getattr(job, "spec", None), "template", None), "spec", None)
    for container in getattr(pod_spec, "containers", None) or []:
        for entry in getattr(container, "env", None) or []:
            secret_ref = getattr(getattr(entry, "value_from", None), "secret_key_ref", None)
            name = getattr(secret_ref, "name", None)
            if isinstance(name, str) and _SENSITIVE_ENV_NAME_INFIX in name:
                return name
    return None


def _reconcile_observed_job(
    *,
    job: object,
    apis: _KubernetesApis,
    namespace: str,
    job_name: str,
) -> None:
    """Finish Secret ownership when create-or-observe finds an accepted Job."""
    secret_name = _job_sensitive_secret_name(job)
    if secret_name is None:
        return
    _install_owner_reference_or_unwind(
        apis=apis,
        namespace=namespace,
        job_name=job_name,
        job_uid=getattr(getattr(job, "metadata", None), "uid", None),
        secret_name=secret_name,
        unwind_on_failure=False,
    )


def _matches_required_model(observed: object, expected: object) -> bool:
    """Compare explicit model fields while tolerating API-populated defaults."""
    if hasattr(expected, "to_dict"):
        expected = expected.to_dict()
    elif hasattr(expected, "__dict__"):
        expected = vars(expected)
    if hasattr(observed, "to_dict"):
        observed = observed.to_dict()
    elif hasattr(observed, "__dict__"):
        observed = vars(observed)
    if isinstance(expected, dict):
        return isinstance(observed, dict) and all(
            _matches_required_model(observed.get(name), wanted)
            for name, wanted in expected.items()
            if wanted is not None
        )
    return observed == expected


def _proxy_security_matches(proxy: object) -> bool:
    """Reject privilege, capability, seccomp and resource-claim overrides."""
    security = getattr(proxy, "security_context", None)
    return (
        not any(
            getattr(security, field, None)
            for field in ("privileged", "proc_mount", "se_linux_options", "windows_options")
        )
        and not getattr(getattr(security, "capabilities", None), "add", None)
        and not getattr(getattr(security, "seccomp_profile", None), "localhost_profile", None)
        and not getattr(getattr(proxy, "resources", None), "claims", None)
    )


def _proxy_startup_matches(proxy: object) -> bool:
    """Permit only the canonical local HTTP startup probe and its API defaults."""
    probe = getattr(proxy, "startup_probe", None)
    http = getattr(probe, "http_get", None)
    return (
        not any(getattr(probe, field, None) for field in ("_exec", "tcp_socket", "grpc"))
        and getattr(probe, "initial_delay_seconds", 0) in (None, 0)
        and getattr(probe, "success_threshold", 1) in (None, 1)
        and not getattr(http, "host", None)
        and not getattr(http, "http_headers", None)
        and getattr(http, "scheme", "HTTP") in (None, "HTTP")
    )


def _matches_database_proxy(pod_spec: object, expected: object | None) -> bool:
    """Compare one native sidecar and reject additional executable or credential fields."""
    proxies = getattr(pod_spec, "init_containers", None) or []
    if expected is None:
        return not proxies
    if len(proxies) != 1:
        return False
    proxy = proxies[0]
    forbidden = (
        "command",
        "env",
        "env_from",
        "volume_mounts",
        "volume_devices",
        "ports",
        "lifecycle",
        "liveness_probe",
        "readiness_probe",
        "working_dir",
        "stdin",
        "tty",
        "stdin_once",
    )
    return (
        not any(getattr(proxy, field, None) for field in forbidden)
        and _proxy_security_matches(proxy)
        and _proxy_startup_matches(proxy)
        and _matches_required_model(proxy, expected)
    )


def _validate_observed_job(
    job: object,
    identity: _JobIdentity,
) -> None:
    """Reject a deterministic-name collision that is not this exact intent."""
    metadata = getattr(job, "metadata", None)
    annotations = getattr(metadata, "annotations", None) or {}
    pod_spec = getattr(getattr(getattr(job, "spec", None), "template", None), "spec", None)
    containers = getattr(pod_spec, "containers", None) or []
    container = containers[0] if len(containers) == 1 else None
    observed = {
        "job_name": getattr(metadata, "name", None),
        "task_identity": annotations.get(_SHIFTER_ANNOTATION_TASK_IDENTITY),
        "service_account_name": getattr(pod_spec, "service_account_name", None) or "",
        "container_name": getattr(container, "name", None),
        "image": getattr(container, "image", None),
        "command": list(getattr(container, "args", None) or []),
        "secret_name": _job_sensitive_secret_name(job),
    }
    expected = {
        "job_name": identity.job_name,
        "task_identity": identity.task_identity,
        "service_account_name": identity.service_account_name,
        "container_name": identity.container_name,
        "image": identity.image,
        "command": identity.command,
        "secret_name": identity.secret_name,
    }
    if observed != expected or not _matches_database_proxy(pod_spec, identity.database_proxy):
        raise CloudTaskError("Observed Kubernetes Job does not match the reserved provisioner launch identity")


def _read_idempotent_job(
    batch_api: object,
    api_exception: type[Exception],
    namespace: str,
    job_name: str,
) -> object | None:
    """Return the named Job if it exists, or ``None`` on a 404."""
    try:
        return _api_call(
            batch_api,
            "read_namespaced_job",
            name=job_name,
            namespace=namespace,
            _request_timeout=_KUBERNETES_REQUEST_TIMEOUT_SECONDS,
        )
    except api_exception as exc:
        if getattr(exc, "status", None) == 404:
            return None
        raise


def _accept_observed_job(launch: _JobLaunch, observed: object) -> tuple[object, str, str | None, bool]:
    """Validate and reconcile a reserved Job found after a create attempt."""
    identity = launch.identity
    if identity is None:
        _cleanup_sensitive_secret(launch.apis.core, launch.secret_name, launch.namespace)
        raise CloudTaskError("Deterministic Job recovery requires a task identity")
    try:
        _validate_observed_job(observed, identity)
    except CloudTaskError:
        _cleanup_sensitive_secret(launch.apis.core, launch.secret_name, launch.namespace)
        raise
    observed_secret_name = _job_sensitive_secret_name(observed)
    if launch.secret_name != observed_secret_name:
        _cleanup_sensitive_secret(launch.apis.core, launch.secret_name, launch.namespace)
    _reconcile_observed_job(
        job=observed,
        apis=launch.apis,
        namespace=launch.namespace,
        job_name=identity.job_name,
    )
    return observed, identity.job_name, observed_secret_name, True


def _observe_reserved_job(launch: _JobLaunch) -> object | None:
    """Read the deterministic Job associated with a launch, when available."""
    identity = launch.identity
    if identity is None:
        return None
    return _read_idempotent_job(
        launch.apis.batch,
        launch.apis.exception,
        launch.namespace,
        identity.job_name,
    )


def _is_retryable_create_conflict(launch: _JobLaunch, create_exc: Exception, attempt: int) -> bool:
    """Return whether a deterministic create hit a transient admission conflict."""
    return (
        launch.identity is not None
        and getattr(create_exc, "status", None) == 409
        and attempt < ADMISSION_CONFLICT_ATTEMPTS - 1
    )


def _create_or_observe_job(launch: _JobLaunch) -> tuple[object, str, str | None, bool]:
    """Create a Job or reconcile the same deterministic Job after ambiguity."""
    for attempt in range(ADMISSION_CONFLICT_ATTEMPTS):
        try:
            created = _api_call(
                launch.apis.batch,
                "create_namespaced_job",
                namespace=launch.namespace,
                body=launch.job,
                _request_timeout=_KUBERNETES_REQUEST_TIMEOUT_SECONDS,
            )
            break
        except Exception as create_exc:
            observed = _observe_reserved_job(launch)
            if observed is not None:
                return _accept_observed_job(launch, observed)
            status = getattr(create_exc, "status", None)
            if _is_retryable_create_conflict(launch, create_exc, attempt):
                # ResourceQuota admission can return an optimistic-concurrency
                # conflict when several Jobs are created together. The Job was
                # not accepted, so retry its deterministic create after a short
                # bounded, jittered delay.
                time.sleep(admission_conflict_backoff_seconds(attempt))
                continue
            if launch.identity is None or status in {400, 401, 403, 405, 406, 415, 422}:
                _cleanup_sensitive_secret(launch.apis.core, launch.secret_name, launch.namespace)
            raise

    job_name = getattr(getattr(created, "metadata", None), "name", None)
    if job_name:
        return created, str(job_name), launch.secret_name, False
    observed = _observe_reserved_job(launch)
    if observed is not None:
        return _accept_observed_job(launch, observed)
    _cleanup_sensitive_secret(launch.apis.core, launch.secret_name, launch.namespace)
    raise CloudTaskError("Kubernetes API did not return a Job name")
