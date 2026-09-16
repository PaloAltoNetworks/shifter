"""Selecting the example range and its logical target through the product.

Target selection goes through ``GET /api/v1/mission-control/range/`` — the same
owner-scoped projection the UI uses — so ownership, active-range, and readiness
checks all apply. Two rules the selection deliberately follows:

* **Never ``instances[0]``.** The target is chosen by its authored logical role.
  Picking the first instance would silently select a host with no declared
  participant access (POLARIS' ``dc01`` is exactly that) and turn a real
  authorization refusal into a confusing check failure.
* **Never a runner-supplied host.** Only the instance ``uuid`` is carried
  forward. The realized host, port, username, and credential stay inside the
  portal, where resolving them is part of what the smoke is testing.
"""

from __future__ import annotations

from dataclasses import dataclass

RANGE_PATH = "/api/v1/mission-control/range/"

_READY = "ready"


class TargetError(RuntimeError):
    """Raised when no owned, ready range with the authored target is available."""


@dataclass(frozen=True)
class RangeTarget:
    """The selected range and logical target. Carries identifiers only."""

    request_id: str
    range_id: int | None
    scenario_id: str
    status: str
    instance_uuid: str
    instance_name: str
    role: str
    os_type: str

    @property
    def ready(self) -> bool:
        return self.status.lower() == _READY


def select_target(payload: dict, *, role: str) -> RangeTarget:
    """Pick the authored logical target out of the range projection.

    A missing range, a non-ready range, or an absent role is an error rather
    than a skip: the smoke's precondition is a known-up example range, and a
    missing precondition must fail the run, never quietly pass it.
    """
    if not payload.get("has_range"):
        raise TargetError("the authenticated actor owns no active range")

    range_payload = payload.get("range") or {}
    status = str(range_payload.get("status", "")).strip().lower()
    if not range_payload:
        raise TargetError("range projection carried no range body")
    if status != _READY or not range_payload.get("is_ready", status == _READY):
        raise TargetError(f"example range is not ready (status: {status or 'unknown'})")

    instances = range_payload.get("instances") or []
    wanted = role.strip().lower()
    matches = [inst for inst in instances if str(inst.get("role", "")).strip().lower() == wanted]
    if not matches:
        available = sorted({str(inst.get("role", "?")) for inst in instances})
        raise TargetError(f"no instance with authored role {wanted!r} in the range (roles present: {available})")
    if len(matches) > 1:
        names = sorted(str(inst.get("name", "?")) for inst in matches)
        raise TargetError(f"role {wanted!r} is ambiguous in this range ({names}); select a range with one such target")

    instance = matches[0]
    uuid = str(instance.get("uuid") or "").strip()
    if not uuid:
        raise TargetError(f"the {wanted!r} instance carries no uuid in the range projection")

    _assert_terminal_offered(payload, uuid)

    return RangeTarget(
        request_id=str(range_payload.get("request_id", "")),
        range_id=range_payload.get("range_id"),
        scenario_id=str(range_payload.get("scenario_id", "")),
        status=status,
        instance_uuid=uuid,
        instance_name=str(instance.get("name", "")),
        role=wanted,
        os_type=str(instance.get("os_type", "")),
    )


def _assert_terminal_offered(payload: dict, instance_uuid: str) -> None:
    """Require the portal's own projection to offer a terminal for the target.

    This is the observable half of "the product exposes this target to this
    participant". The declared-channel binding itself is enforced inside
    ``engine.services``; a violation surfaces later as a refusal, which the
    relevant check records rather than masking here.
    """
    offered = {str(entry.get("uuid") or "") for entry in payload.get("connection_urls") or []}
    if instance_uuid not in offered:
        raise TargetError("the range projection offers no terminal connection for the selected target")
