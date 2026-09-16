"""Event spare-range pool (issue #1018 revised plan).

Formalizes the previously hand-made "fake user owns a spare range" process:
each spare range in an event's recovery pool is owned by a dedicated,
auto-created **managed system user** -- never a
:class:`~ctf.models.CTFParticipant` -- until it is consumed during recovery,
at which point ownership transfers to the recovering participant (via the
existing :func:`ctf.bridges.cms_reassign_range_owner`) and the freed managed
user is deleted.

A spare's ``status`` starts at ``provisioning`` and is flipped to ``ready``/
``failed`` by :func:`ctf.signals.sync_ctf_spare_range_status` when CMS
reports the underlying range's status change (the same
``cms.services.range_status_changed`` projection that already keeps
``CTFParticipant.range_status`` in sync) -- no separate polling loop is
introduced here.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from ctf.enums import SpareRangeStatus
from ctf.exceptions import CTFNotFoundError
from ctf.models import CTFEvent, CTFSpareRange
from ctf.services.audit import audit_spare_provisioning
from shared.log_sanitize import safe_log_value

if TYPE_CHECKING:
    from django.contrib.auth.models import User

logger = logging.getLogger(__name__)

# Marks a managed spare user unambiguously so it can never be mistaken for a
# real participant/organizer account, and so deletion helpers refuse to touch
# anything else.
_SPARE_USER_EMAIL_DOMAIN = "ctf-spare.invalid"

# A spare counts against the pool while it is still usable or on its way to
# being usable; failed/consumed spares are excluded from "existing" counts so
# a top-up replaces them.
_ACTIVE_SPARE_STATUSES = (SpareRangeStatus.PROVISIONING.value, SpareRangeStatus.READY.value)

# Fixed namespace so a spare's capacity draw key is derived deterministically
# from its managed user and never collides with a participant id.
_SPARE_DRAW_NAMESPACE = UUID("6f9d1f5e-0f3a-4d33-9a2f-2f1c9c4a7b10")


def create_managed_spare_user() -> User:
    """Create a dedicated, inactive system user to own one pooled spare range.

    Never a :class:`~ctf.models.CTFParticipant` and never active -- the
    ``@ctf-spare.invalid`` email domain is the machine-checkable marker used
    by :func:`delete_managed_spare_user` and by any surface that must exclude
    these accounts (participant lists, scoreboards, invites).
    """
    from django.contrib.auth.models import User

    token = uuid4().hex
    user = User.objects.create_user(
        username=f"ctf-spare-{token}",
        email=f"{token}@{_SPARE_USER_EMAIL_DOMAIN}",
        is_active=False,
    )
    user.set_unusable_password()
    user.save(update_fields=["password"])
    logger.info("Created managed spare user id=%s", safe_log_value(user.pk))
    return user


def delete_managed_spare_user(user: User | None) -> bool:
    """Best-effort hard-delete of a freed managed spare user.

    Refuses to delete anything that is not marked as a managed spare user
    (belt-and-braces against ever deleting a real account). Failures are
    logged and swallowed -- called after ownership has already moved off the
    user, so a cleanup failure here must never fail the surrounding recovery
    or provisioning operation.
    """
    if user is None:
        return False
    if not user.email.endswith(f"@{_SPARE_USER_EMAIL_DOMAIN}"):
        logger.warning(
            "delete_managed_spare_user: refusing to delete non-spare user id=%s",
            safe_log_value(user.pk),
        )
        return False

    result = True
    try:
        user.delete()
    except Exception:
        logger.exception(
            "delete_managed_spare_user: failed to delete spare user id=%s",
            safe_log_value(user.pk),
        )
        result = False
    return result


def _get_event(event_id: UUID) -> CTFEvent:
    """Look up a `CTFEvent` by id, raising `CTFNotFoundError` if it does not exist."""
    try:
        return CTFEvent.objects.get(pk=event_id)
    except CTFEvent.DoesNotExist:
        raise CTFNotFoundError(
            f"Event {event_id} not found",
            details={"event_id": str(event_id)},
        ) from None


def _spare_draw_key(spare_user: User) -> UUID:
    """Return the stable capacity draw key for one spare.

    The managed spare user is created once per spare and never reused, so its
    id is a stable identity for the draw. It is hashed into a UUID because the
    ledger key is a UUID column shared with participant-scoped draws.
    """
    from uuid import uuid5

    return uuid5(_SPARE_DRAW_NAMESPACE, str(spare_user.pk))


def _provision_one_spare(event: CTFEvent) -> CTFSpareRange:
    """Create one managed spare user + CMS range, recording a CTFSpareRange row.

    Mirrors ``ctf.services.range.provision.provision_participant_range``'s
    range_config extraction. Provisioning failures are recorded as a
    ``failed`` spare rather than raised, so one bad attempt does not abort
    the rest of a top-up.
    """
    from ctf.bridges import cms_create_range, cms_find_range_instance_id

    spare_user = create_managed_spare_user()
    agents_by_os = event.range_config.get("agents_by_os", {}) if event.range_config else {}
    ngfw_enabled = event.range_config.get("ngfw_enabled", False) if event.range_config else False

    # PLAT-201: a spare occupies a range slot like any other, so it draws from
    # the same event budget. Keyed on the managed spare user, which is stable
    # for this spare and known before the range exists.
    from ctf.services.range.capacity import admit_range, release_range

    draw_key = _spare_draw_key(spare_user)
    admission = admit_range(event.pk, draw_key)
    if admission is not None and admission["blocking"]:
        logger.warning(
            "provision_event_spares: capacity refused a spare for event=%s codes=%s",
            safe_log_value(event.pk),
            admission["reason_codes"],
        )
        return CTFSpareRange.objects.create(
            event=event,
            owner_user=spare_user,
            status=SpareRangeStatus.FAILED.value,
        )

    try:
        result = cms_create_range(
            user=spare_user,
            scenario=event.scenario_id,
            agents_by_os=agents_by_os,
            ngfw_enabled=ngfw_enabled,
            remote_access_teardown_at=event.get_cleanup_time(),
        )
    except Exception:
        logger.exception(
            "provision_event_spares: range provisioning failed for event=%s",
            safe_log_value(event.pk),
        )
        # No range came up, so the draw must go back.
        release_range(draw_key)
        return CTFSpareRange.objects.create(
            event=event,
            owner_user=spare_user,
            status=SpareRangeStatus.FAILED.value,
        )

    range_instance_id = cms_find_range_instance_id(result.request_id)
    return CTFSpareRange.objects.create(
        event=event,
        owner_user=spare_user,
        range_instance_id=range_instance_id,
        request_id=result.request_id,
        status=SpareRangeStatus.PROVISIONING.value,
    )


def provision_event_spares(event_id: UUID, target_count: int, *, operator: User | None = None) -> dict[str, Any]:
    """Top up an event's spare-range pool to ``target_count``.

    Sets ``event.spare_range_count = target_count`` and creates
    ``max(0, target_count - existing)`` new spares, each under a fresh
    managed spare user. ``existing`` counts only non-consumed, non-failed
    spares, so a prior failed attempt is replaced rather than counted toward
    the target. Writes one audit row for the top-up action as a whole (not
    one per range -- CMS already audits each individual range creation).

    Args:
        event_id: UUID of the event.
        target_count: Desired pool size.
        operator: Operator initiating the top-up (audit actor), if any.

    Returns:
        Dict with ``event_id``, ``target_count``, ``existing``, ``created``.

    Raises:
        CTFNotFoundError: If the event does not exist.
    """
    from ctf.services.range.capacity import assess_declared_capacity, declare_event_capacity

    event = _get_event(event_id)
    if operator is not None:
        # Interactive top-up: assert the ranges capability at the service
        # boundary as well as the view (defense in depth, #1922).
        from ctf.enums import EventCapability
        from ctf.services.authorization import assert_event_capability

        assert_event_capability(operator.pk, event, EventCapability.RANGES)
    event.spare_range_count = target_count
    event.save(update_fields=["spare_range_count", "updated_at"])
    # Declare AFTER persisting the new target: the declaration's
    # expected_concurrent_ranges is roster + spare pool, so declaring first
    # published the previous pool size and understated the peak by exactly the
    # change (PLAT-201 preflight). Still before any spare spins up.
    declare_event_capacity(event_id, source="spare_pool")
    # PLAT-201: growing the spare pool raises peak concurrent ranges, so a
    # top-up is a capacity-relevant change and gets the same admission check as
    # a participant wave.
    capacity = assess_declared_capacity(event_id, source="spare_pool")
    if capacity is not None and capacity["blocking"]:
        logger.warning(
            "provision_event_spares: capacity refused top-up for event=%s codes=%s",
            safe_log_value(event_id),
            capacity["reason_codes"],
        )
        return {
            "event_id": str(event.pk),
            "target_count": target_count,
            "existing": CTFSpareRange.objects.filter(event=event, status__in=_ACTIVE_SPARE_STATUSES).count(),
            "created": 0,
            # Bounded codes only. The partition name is deployment topology and
            # stays on the operator-only assessment record (PLAT-201 preflight).
            "capacity_reason_codes": capacity["reason_codes"],
            "refused": True,
        }

    existing = CTFSpareRange.objects.filter(event=event, status__in=_ACTIVE_SPARE_STATUSES).count()
    to_create = max(0, target_count - existing)

    logger.info(
        "provision_event_spares: event=%s target=%s existing=%d creating=%d",
        safe_log_value(event_id),
        safe_log_value(target_count),
        existing,
        to_create,
    )

    created = 0
    for _ in range(to_create):
        spare = _provision_one_spare(event)
        if spare.status != SpareRangeStatus.FAILED.value:
            created += 1

    audit_spare_provisioning(
        actor_id=operator.id if operator is not None else None,
        event_id=event.pk,
        target_count=target_count,
        existing=existing,
        created=created,
    )

    return {
        "event_id": str(event.pk),
        "target_count": target_count,
        "existing": existing,
        "created": created,
    }


def get_event_spare_summary(event_id: UUID) -> dict[str, Any]:
    """Return spare-pool counts by status plus an available-for-assignment count.

    Bounded operator diagnostics for the admin surface (a later chunk
    consumes it) -- no range/provider detail beyond counts and ids.

    Raises:
        CTFNotFoundError: If the event does not exist.
    """
    event = _get_event(event_id)
    spares = CTFSpareRange.objects.filter(event=event)

    counts = {status.value: 0 for status in SpareRangeStatus}
    for status_value in spares.values_list("status", flat=True):
        counts[status_value] = counts.get(status_value, 0) + 1

    available = spares.filter(status=SpareRangeStatus.READY.value, consumed_by__isnull=True).count()

    return {
        "event_id": str(event.pk),
        "target_count": event.spare_range_count,
        "counts": counts,
        "available": available,
    }


def cleanup_event_spares(event_id: UUID) -> dict[str, Any]:
    """Tear down every unconsumed spare range for an event and free its managed user.

    Consumed spares are left alone -- their range now belongs to a
    participant and is torn down (if at all) through the normal
    participant-range cleanup path, not here.

    Args:
        event_id: UUID of the event.

    Returns:
        Dict with counts of destroyed ranges, users deleted, and failures.

    Raises:
        CTFNotFoundError: If the event does not exist.
    """
    from ctf.bridges import cms_destroy_range

    event = _get_event(event_id)
    unconsumed = CTFSpareRange.objects.filter(event=event, consumed_by__isnull=True).exclude(
        status=SpareRangeStatus.FAILED.value
    )

    destroyed = 0
    users_deleted = 0
    failed = 0

    for spare in unconsumed:
        owner = spare.owner_user
        try:
            if spare.range_instance_id is not None and owner is not None:
                cms_destroy_range(owner, spare.range_instance_id)
            destroyed += 1
        except Exception:
            failed += 1
            logger.exception(
                "cleanup_event_spares: failed to destroy spare range_instance_id=%s (event=%s)",
                spare.range_instance_id,
                safe_log_value(event_id),
            )
        if delete_managed_spare_user(owner):
            users_deleted += 1
        spare.status = SpareRangeStatus.FAILED.value
        spare.owner_user = None
        spare.save(update_fields=["status", "owner_user", "updated_at"])

    logger.info(
        "cleanup_event_spares: event=%s destroyed=%d users_deleted=%d failed=%d",
        safe_log_value(event_id),
        destroyed,
        users_deleted,
        failed,
    )

    return {
        "event_id": str(event.pk),
        "destroyed": destroyed,
        "users_deleted": users_deleted,
        "failed": failed,
    }
