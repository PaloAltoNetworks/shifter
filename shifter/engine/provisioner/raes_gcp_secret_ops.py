"""Provisioner-managed SSH secret operation bindings for the RAES GCE backend.

Extracted from ``raes_gcp_apply.py`` (Sonar S104) into its own leaf module so
both the apply and destroy sides (``raes_gcp_apply``, ``raes_gcp_destroy``) can
import the shared SSH-secret contract without either module depending on the
other -- mirrors ``gcp_range_cell_credentials`` for the cyberscript backend,
which the same apply/destroy pair there both import from.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from gcp_guest_secrets import delete_raes_ssh_secret, ensure_raes_ssh_secret

__all__ = ["RaesGceSecretOps", "_default_secret_ops"]


@dataclass(frozen=True)
class RaesGceSecretOps:
    """Provisioner-managed SSH secret operations for the RAES range-cell backend.

    Keyed on ``(range_id, instance_key)`` -- the RAES instance key (node address +
    count index), never a cyberscript ``ScenarioInstance``. Injectable so tests
    exercise the orchestration without touching Secret Manager.
    """

    ensure_ssh: Callable[[int, str], tuple[str, str]]
    delete_ssh: Callable[[int, str], None]


def _default_secret_ops() -> RaesGceSecretOps:
    """Return the production RAES SSH-secret operation bindings."""
    return RaesGceSecretOps(ensure_ssh=ensure_raes_ssh_secret, delete_ssh=delete_raes_ssh_secret)
