"""GKE-native Kubernetes Job adapter implementing TaskRunner protocol.

Split into a package (#561) so no module exceeds 500 lines. The
implementation is spread across private submodules by responsibility:

- ``_types``: transient dataclasses/protocols shared across submodules.
- ``_helpers``: constants and small stateless helpers.
- ``_job_manifest``: Job/Pod/Container/Secret manifest builders.
- ``_job_lifecycle``: observe/validate/create-or-observe for deterministic Jobs.
- ``_secrets``: sensitive-env Secret naming, creation, ownership, and unwind.
- ``_status``: ``get_task_status`` support.
- ``_run_task_flow``: ``run_task`` orchestration.
- ``_runner``: the ``GCPTaskRunner`` class itself.

This module re-exports the public surface so callers keep using
``from shared.cloud.gcp.task_runner import GCPTaskRunner`` exactly as before
the split.
"""

from __future__ import annotations

from shared.cloud import PROVISIONER_CONTAINER_NAME

from ._runner import GCPTaskRunner

__all__ = ("PROVISIONER_CONTAINER_NAME", "GCPTaskRunner")
