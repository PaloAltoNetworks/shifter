"""Read-only range/instance queries (system-level, no user-ownership enforcement).

Used by CTF to query range state without requiring the range owner's User.
"""

from __future__ import annotations

from uuid import UUID

from cms.models import RangeInstance


def get_range_status_by_id(range_instance_id: int) -> str:
    """Get the current status of a RangeInstance by its PK.

    Returns:
        Status string, or ``"unknown"`` if not found.
    """
    try:
        # all_objects: status lookups must see soft-deleted (terminal/destroyed)
        # ranges so callers can report the final lifecycle state of a torn-down range.
        return str(RangeInstance.all_objects.values_list("status", flat=True).get(pk=range_instance_id))
    except RangeInstance.DoesNotExist:
        return "unknown"


def get_range_spec_by_id(range_instance_id: int) -> dict | None:
    """Get the range_spec dict from a RangeInstance by its PK.

    Returns:
        The range_spec dict, or ``None`` if not found.
    """
    try:
        # all_objects: range_spec lookups must see soft-deleted (terminal)
        # ranges so callers can correlate audit events to a torn-down range.
        spec = RangeInstance.all_objects.values_list("range_spec", flat=True).get(pk=range_instance_id)
        return spec if spec is None or isinstance(spec, dict) else None
    except RangeInstance.DoesNotExist:
        return None


def find_range_instance_id_by_request(request_id: str | UUID) -> int | None:
    """Find a RangeInstance PK by its provisioning request ID.

    Returns:
        The RangeInstance PK, or ``None`` if not found.
    """
    # all_objects: callback correlation needs to find ranges by request even
    # after the range has reached a terminal soft-deleted state.
    pk = (
        RangeInstance.all_objects.filter(
            request__request_id=request_id,
        )
        .values_list("pk", flat=True)
        .first()
    )
    return int(pk) if pk is not None else None


def get_range_target_instances(user_id: int) -> list[dict[str, str]]:
    """Get the accessible provisioned instances for a user's ready range.

    Normally these are the non-attacker targets: multi-node scenarios (e.g.
    POLARIS) hide the attacker workstation and expose the targets the
    participant works against. A single-seat purple-team lab (e.g. TechVault),
    however, provisions only the attacker-tagged seat host that the participant
    works *from* (VS Code Desktop over RDP). In that case there are no
    non-attacker instances, so fall back to returning the seat host(s) —
    otherwise the participant's range page renders empty with no way to reach
    their environment.

    Args:
        user_id: PK of the user.

    Returns:
        List of dicts with name, private_ip, os_type for each accessible instance.
    """
    from engine.services import get_user_ready_range_instances

    instances = list(get_user_ready_range_instances(user_id))
    targets = [inst for inst in instances if inst.get("role") != "attacker"]
    return targets if targets else instances
