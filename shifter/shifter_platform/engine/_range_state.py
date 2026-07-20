"""Range status predicates and realized-instance projections (#685).

Pure, dependency-free helpers that classify a persisted range status or
project the raw ``provisioned_instances`` payload into the bounded shapes
callers need. Both the model compatibility wrappers on ``engine.models.Range``
and the ``engine.services`` layer that operates on ``Range`` consume this
module, so it lives directly under ``engine`` (below both) rather than inside
``engine.services`` -- putting it there would make the model import from a
private submodule of the layer that already depends on the model, concealing
a model-to-service reverse dependency behind a function-local import.

These functions must stay free of ORM, settings, secret-store, network,
logging, or audit side effects (see the #685 architecture preflight).
"""

from __future__ import annotations

from typing import Any

from shared.enums import TERMINAL_STATUSES, ResourceStatus


def is_range_usable(status: str) -> bool:
    """Return True when a range is operational and connectable (ready or paused).

    Pure classification over the canonical ``shared.enums.ResourceStatus``
    vocabulary. Moved off ``engine.models.Range.is_usable`` (#685) so status
    policy is not duplicated on the model.
    """
    return status in (ResourceStatus.READY, ResourceStatus.PAUSED)


def is_range_terminal(status: str) -> bool:
    """Return True when a range has reached a final state (destroyed or failed).

    Pure classification over the canonical ``shared.enums.TERMINAL_STATUSES``
    grouping. Moved off ``engine.models.Range.is_terminal`` (#685).
    """
    return status in TERMINAL_STATUSES


# ---------------------------------------------------------------------------
# Realized-instance projection over ``engine.models.Range.provisioned_instances``.
#
# These pure helpers traverse the provisioner-owned realized instance list.
# They moved off ``engine.models.Range`` (#685) so the model stays
# persistence-focused. They take an already-loaded instances list (or
# ``None``) and return the raw payload dict for callers that need it
# (terminal/connection lookup); higher layers consume the bounded connection
# projections in ``engine.services._common``, not the raw dicts.
# ---------------------------------------------------------------------------


def find_instance_by_role(instances: list[dict[str, Any]] | None, role: str) -> dict[str, Any] | None:
    """Return the first realized instance payload with the given role, or ``None``."""
    if not instances:
        return None
    for instance in instances:
        if instance.get("role") == role:
            return instance
    return None


def find_instance_by_uuid(instances: list[dict[str, Any]] | None, uuid: str) -> dict[str, Any] | None:
    """Return the realized instance payload with the given UUID, or ``None``.

    Raises ``ValueError`` when ``uuid`` is empty, matching the historical
    ``Range.get_instance_by_uuid`` contract.
    """
    if not uuid:
        raise ValueError("uuid is required")
    if not instances:
        return None
    for instance in instances:
        if instance.get("uuid") == uuid:
            return instance
    return None


def attacker_instance(instances: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    """Return the attacker instance payload, or ``None``."""
    return find_instance_by_role(instances, "attacker")


def victim_instances(instances: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Return all victim instance payloads (empty list when none)."""
    if not instances:
        return []
    return [instance for instance in instances if instance.get("role") == "victim"]


def attacker_private_ip(instances: list[dict[str, Any]] | None) -> str | None:
    """Return the attacker instance private IP, or ``None``."""
    attacker = attacker_instance(instances)
    if not attacker:
        return None
    return attacker.get("private_ip")


def first_victim_private_ip(instances: list[dict[str, Any]] | None) -> str | None:
    """Return the first victim instance private IP, or ``None``."""
    victims = victim_instances(instances)
    if not victims:
        return None
    return victims[0].get("private_ip")
