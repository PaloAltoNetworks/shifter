"""``run_task`` orchestration: resolve inputs, reconcile an existing
deterministic Job, or build and submit a new one.

Extracted from the GCP task-runner package (#1824).
"""

from __future__ import annotations

import logging

from shared.cloud.sensitive_env import split_env

from ._job_lifecycle import (
    _create_or_observe_job,
    _read_idempotent_job,
    _reconcile_observed_job,
    _validate_observed_job,
)
from ._job_manifest import _build_env, _build_job
from ._profile import KubernetesTaskProfile
from ._secrets import (
    _build_secret_name,
    _cleanup_sensitive_secret,
    _ensure_sensitive_secret,
    _install_owner_reference_or_unwind,
)
from ._types import _JobIdentity, _JobLaunch, _KubernetesApis, _RunTaskContext, _TaskLaunchRequest
from .naming import build_idempotent_job_name

logger = logging.getLogger(__name__)


def _build_run_context(
    apis: _KubernetesApis,
    request: _TaskLaunchRequest,
    profile: KubernetesTaskProfile,
) -> _RunTaskContext:
    """Derive deterministic launch identities for one TaskRunner invocation."""
    sensitive_env, _plain_env = split_env(request.env_overrides or {})
    secret_name = _build_secret_name(request.container_name, request.task_identity) if sensitive_env else None
    identity = None
    if request.task_identity:
        identity = _JobIdentity(
            job_name=build_idempotent_job_name(request.container_name, request.task_identity),
            task_identity=request.task_identity,
            image=request.image,
            command=request.command,
            container_name=request.container_name,
            service_account_name=profile.service_account_name,
            secret_name=secret_name,
        )
    return _RunTaskContext(
        apis=apis,
        namespace=request.namespace,
        image=request.image,
        command=request.command,
        container_name=request.container_name,
        env_overrides=request.env_overrides,
        task_identity=request.task_identity,
        identity=identity,
        sensitive_env=sensitive_env,
        secret_name=secret_name,
        profile=profile,
    )


def _existing_task_ref(context: _RunTaskContext) -> str | None:
    """Reconcile and return an already accepted deterministic Job."""
    identity = context.identity
    if identity is None:
        return None
    observed = _read_idempotent_job(
        context.apis.batch,
        context.apis.exception,
        context.namespace,
        identity.job_name,
    )
    if observed is None:
        return None
    _validate_observed_job(observed, identity)
    if context.sensitive_env and context.secret_name is not None:
        _ensure_sensitive_secret(
            apis=context.apis,
            namespace=context.namespace,
            secret_name=context.secret_name,
            sensitive_env=context.sensitive_env,
            container_name=context.container_name,
            task_identity=context.task_identity,
            runner_label_value=context.profile.runner_label_value,
        )
    _reconcile_observed_job(
        job=observed,
        apis=context.apis,
        namespace=context.namespace,
        job_name=identity.job_name,
    )
    return f"{context.namespace}/{identity.job_name}"


def _build_launch_job(context: _RunTaskContext) -> object:
    """Create sensitive state and build the corresponding Job manifest."""
    if context.sensitive_env:
        assert context.secret_name is not None, "sensitive env requires a derived Secret name"
        _ensure_sensitive_secret(
            apis=context.apis,
            namespace=context.namespace,
            secret_name=context.secret_name,
            sensitive_env=context.sensitive_env,
            container_name=context.container_name,
            task_identity=context.task_identity,
            runner_label_value=context.profile.runner_label_value,
        )
    try:
        env = _build_env(
            context.apis.client,
            context.env_overrides,
            sensitive_secret_name=context.secret_name,
        )
        return _build_job(
            context.apis.client,
            context.image,
            context.container_name,
            context.command,
            env,
            context.profile,
            task_identity=context.task_identity,
        )
    except Exception:
        _cleanup_sensitive_secret(context.apis.core, context.secret_name, context.namespace)
        raise


def _submit_launch_job(context: _RunTaskContext, job: object) -> str:
    """Submit a built Job and finish ownership of any sensitive Secret."""
    launch = _JobLaunch(
        apis=context.apis,
        namespace=context.namespace,
        job=job,
        identity=context.identity,
        secret_name=context.secret_name,
    )
    created, job_name, effective_secret_name, owner_reconciled = _create_or_observe_job(launch)
    if effective_secret_name is not None and not owner_reconciled:
        _install_owner_reference_or_unwind(
            apis=context.apis,
            namespace=context.namespace,
            job_name=job_name,
            job_uid=getattr(getattr(created, "metadata", None), "uid", None),
            secret_name=effective_secret_name,
        )
    task_ref = f"{context.namespace}/{job_name}"
    logger.info("run_task: started job=%s image=%s", task_ref, context.image)
    return task_ref


def _run_task(context: _RunTaskContext) -> str:
    """Reconcile an existing Job or submit a newly built manifest."""
    existing_ref = _existing_task_ref(context)
    if existing_ref is not None:
        return existing_ref
    return _submit_launch_job(context, _build_launch_job(context))
