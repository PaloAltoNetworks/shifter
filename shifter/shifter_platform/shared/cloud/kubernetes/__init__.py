"""Provider-neutral Kubernetes task runner (#1824).

This package holds the generic Kubernetes Job mechanics — manifest construction,
create-or-observe lifecycle, ambiguous-create recovery, sensitive-env Secret
projection, foreground interrupt, and status mapping — previously scoped under
``shared.cloud.gcp``. It has no ``shared.cloud.gcp.*`` or AWS imports and reads no
Django settings; every provider-variable choice is injected through a
``KubernetesTaskProfile``.

It is an internal implementation dependency for Kubernetes-backed cloud adapters,
not a new public task-orchestration API. ``shared.cloud.get_task_runner()`` and
``shared.cloud.types.TaskRunner`` remain the only task interface.
"""

from __future__ import annotations

from ._profile import KubernetesTaskProfile, ProvisionerHardeningProfile, standard_provisioner_hardening
from ._runner import KubernetesTaskRunner

__all__ = (
    "KubernetesTaskProfile",
    "KubernetesTaskRunner",
    "ProvisionerHardeningProfile",
    "standard_provisioner_hardening",
)
