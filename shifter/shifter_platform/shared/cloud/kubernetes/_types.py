"""Shared dataclasses and protocols for the neutral Kubernetes task-runner package.

These types describe transient, per-launch state passed between the
``KubernetesTaskRunner`` class (see ``_runner``) and the module-level helper
functions the launch/observe/reconcile logic is split across
(``_job_manifest``, ``_job_lifecycle``, ``_secrets``, ``_run_task_flow``).
None of them carry behavior of their own.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ._profile import KubernetesTaskProfile


@dataclass(frozen=True)
class _KubernetesApis:
    """Dynamically loaded Kubernetes API objects used during one launch."""

    batch: object
    core: object
    client: object
    exception: type[Exception]


class _OwnerReference(Protocol):
    """Attributes serialized from the dynamically loaded Kubernetes model."""

    api_version: object
    kind: object
    name: object
    uid: object
    controller: object
    block_owner_deletion: object


@dataclass(frozen=True)
class _JobIdentity:
    """Expected immutable identity of a deterministic task Job."""

    job_name: str
    task_identity: str
    image: str
    command: list[str]
    container_name: str
    service_account_name: str
    secret_name: str | None


@dataclass(frozen=True)
class _TaskLaunchRequest:
    """The already-validated inputs for one ``run_task`` invocation.

    Bundling these keeps ``_build_run_context`` within the parameter budget and
    reads as one cohesive "what to launch" descriptor.
    """

    namespace: str
    image: str
    command: list[str]
    container_name: str
    env_overrides: dict[str, str] | None
    task_identity: str | None


@dataclass(frozen=True)
class _JobLaunch:
    """Inputs shared by create and ambiguous-create recovery."""

    apis: _KubernetesApis
    namespace: str
    job: object
    identity: _JobIdentity | None
    secret_name: str | None


@dataclass(frozen=True)
class _RunTaskContext:
    """Resolved Kubernetes inputs for one TaskRunner invocation."""

    apis: _KubernetesApis
    namespace: str
    image: str
    command: list[str]
    container_name: str
    env_overrides: dict[str, str] | None
    task_identity: str | None
    identity: _JobIdentity | None
    sensitive_env: dict[str, str]
    secret_name: str | None
    profile: KubernetesTaskProfile
