"""Provisioner-managed SSH secret operation bindings for the ACES GCE backend.

Extracted from ``aces_gcp_apply.py`` (Sonar S104) into its own leaf module so
both the apply and destroy sides (``aces_gcp_apply``, ``aces_gcp_destroy``) can
import the shared SSH-secret contract without either module depending on the
other -- mirrors ``gcp_range_cell_credentials`` for the cyberscript backend,
which the same apply/destroy pair there both import from.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from gcp_guest_secrets import delete_aces_ssh_secret, ensure_aces_ssh_secret

__all__ = ["AcesGceSecretOps", "_default_secret_ops"]


@dataclass(frozen=True)
class AcesGceSecretOps:
    """Provisioner-managed SSH secret operations for the ACES range-cell backend.

    Keyed on ``(range_id, instance_key)`` -- the ACES instance key (node address +
    count index), never a cyberscript ``ScenarioInstance``. Injectable so tests
    exercise the orchestration without touching Secret Manager.
    """

    ensure_ssh: Callable[[int, str], tuple[str, str]]
    delete_ssh: Callable[[int, str], None]


def _default_secret_ops() -> AcesGceSecretOps:
    """Return the production ACES SSH-secret operation bindings."""
    return AcesGceSecretOps(ensure_ssh=ensure_aces_ssh_secret, delete_ssh=delete_aces_ssh_secret)
