"""Isolated Kubernetes Jobs that acquire backend-owned feature artifacts (ADR-034-R12).

One Job per claimed acquisition attempt, in its own namespace with its own
service account, admission policy and egress policy. The Job runs a pinned,
Django-free command, holds no database access, and may only write the
content-addressed delivery prefix. The provisioner launcher creates it, reads its
single result line, and deletes it once terminal.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from shared.cloud.exceptions import CloudTaskError
from shared.cloud.kubernetes import KubernetesTaskProfile, KubernetesTaskRunner, ProvisionerHardeningProfile
from shared.cloud.kubernetes.naming import build_idempotent_job_name
from shared.feature_artifacts.job import AcquisitionResult, parse_result

logger = logging.getLogger(__name__)

ACQUISITION_NAMESPACE = "shifter-acquisition"
ACQUISITION_CONTAINER = "feature-artifact-acquisition"
ACQUISITION_SERVICE_ACCOUNT = "artifact-acquirer"
ACQUISITION_COMMAND = ("python", "-m", "shared.feature_artifacts.job")
#: The Job's only writable path: a dedicated disk-backed scratch volume, not a
#: shared temporary directory. HOME and TMPDIR point here.
ACQUISITION_WORKDIR = "/work"
_PLATFORM_UID = 1000


def acquisition_task_profile() -> KubernetesTaskProfile:
    """Fixed posture for every acquisition Job; nothing in it comes from a pack."""
    return KubernetesTaskProfile(
        runner_label_value=ACQUISITION_CONTAINER,
        service_account_name=ACQUISITION_SERVICE_ACCOUNT,
        image_pull_policy="IfNotPresent",
        backoff_limit=0,
        ttl_seconds_after_finished=600,
        hardening=ProvisionerHardeningProfile(
            container_name=ACQUISITION_CONTAINER,
            run_as_uid=_PLATFORM_UID,
            run_as_gid=_PLATFORM_UID,
            # Disk-backed scratch for the downloaded tarball and extracted artifact;
            # the root filesystem stays read-only.
            writable_mounts=(("work", ACQUISITION_WORKDIR, None, "4Gi"),),
        ),
        resource_requests={"cpu": "250m", "memory": "256Mi", "ephemeral-storage": "1Gi"},
        resource_limits={"cpu": "2", "memory": "1Gi", "ephemeral-storage": "4Gi"},
        active_deadline_seconds=1800,
        container_command=ACQUISITION_COMMAND,
    )


def acquisition_args(source_name: str, resolved_version: str, platform: str) -> list[str]:
    """The Job's only inputs: the inventory row's resolved identity."""
    return [source_name, resolved_version, platform]


def acquisition_task_identity(attempt: UUID, image: str, args: list[str]) -> dict[str, Any]:
    """Identity derives exclusively from the claimed attempt and the pinned image."""
    return {
        "task_identity": str(attempt),
        "service_account_name": ACQUISITION_SERVICE_ACCOUNT,
        "container_name": ACQUISITION_CONTAINER,
        "image": image,
        "command": args,
    }


def acquisition_task_ref(attempt: UUID) -> str:
    """Deterministic Job reference for one attempt (create-or-observe safe)."""
    return f"{ACQUISITION_NAMESPACE}/{build_idempotent_job_name(ACQUISITION_CONTAINER, str(attempt))}"


def launch_acquisition(
    attempt: UUID, *, image: str, args: list[str], env: dict[str, str], runner: KubernetesTaskRunner | None = None
) -> None:
    """Idempotently create (or observe) the Job for ``attempt``."""
    (runner or KubernetesTaskRunner(acquisition_task_profile())).run_task(
        task_definition=image,
        cluster=ACQUISITION_NAMESPACE,
        command=args,
        container_name=ACQUISITION_CONTAINER,
        env_overrides=env,
        task_identity=str(attempt),
    )


def observe_acquisition(
    attempt: UUID, *, image: str, args: list[str], runner: KubernetesTaskRunner | None = None
) -> AcquisitionResult | None:
    """Return the Job's reported result once terminal, ``None`` while it runs.

    A Job that ended without a readable result line (crash, deadline, eviction)
    is reported as a failed acquisition, never as success.
    """
    runner = runner or KubernetesTaskRunner(acquisition_task_profile())
    identity = acquisition_task_identity(attempt, image, args)
    try:
        raw = runner.get_task_output(ACQUISITION_NAMESPACE, acquisition_task_ref(attempt), identity)
    except CloudTaskError as exc:
        if str(exc) != "Task execution failed":
            raise
        return AcquisitionResult(ok=False, reason="acquisition Job failed without a result")
    if raw is None:
        return None
    result = parse_result(raw.decode("utf-8", errors="replace"))
    return result or AcquisitionResult(ok=False, reason="acquisition Job produced no valid result")


def cleanup_acquisition(
    attempt: UUID, *, image: str, args: list[str], runner: KubernetesTaskRunner | None = None
) -> None:
    """Delete a terminal Job after its result was consumed; TTL is the fallback."""
    runner = runner or KubernetesTaskRunner(acquisition_task_profile())
    try:
        runner.delete_completed_task(
            ACQUISITION_NAMESPACE, acquisition_task_ref(attempt), acquisition_task_identity(attempt, image, args)
        )
    except CloudTaskError as exc:
        logger.warning("feature artifact acquisition cleanup deferred attempt=%s reason=%s", attempt, exc)
