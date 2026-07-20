"""Server-owned range leases shared by Mission Control and CTF."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from django.db import transaction
from django.utils import timezone

from cms.exceptions import CMSError
from cms.models import RangeInstance
from shared.audit import AuditAction, AuditActorType, AuditEntityType, AuditEvent
from shared.enums import RangeSource, ResourceStatus
from shared.log_sanitize import safe_log_id

if TYPE_CHECKING:
    from django.contrib.auth.models import User

logger = logging.getLogger(__name__)

MISSION_CONTROL_INITIAL_DAYS = 30
MISSION_CONTROL_EXTENSION_DAYS = 30
MISSION_CONTROL_MAXIMUM_DAYS = 365


class RangeLeaseNotFound(CMSError):
    """The caller has no active Mission Control lease."""


class RangeLeaseConflict(CMSError):
    """The range lease cannot be extended in its current state."""


@dataclass(frozen=True)
class RangeLease:
    """Trusted lease values attached to one range generation."""

    expires_at: datetime
    maximum_expires_at: datetime
    extension_days: int


@dataclass(frozen=True)
class RangeLeaseProjection:
    """Safe lifecycle fields exposed to the Mission Control SPA."""

    expires_at: datetime
    maximum_expires_at: datetime
    extension_days: int
    can_extend: bool

    def to_payload(self) -> dict[str, object]:
        return {
            "expires_at": self.expires_at.isoformat().replace("+00:00", "Z"),
            "maximum_expires_at": self.maximum_expires_at.isoformat().replace("+00:00", "Z"),
            "extension_days": self.extension_days,
            "can_extend": self.can_extend,
        }


def build_range_lease(
    range_source: RangeSource,
    *,
    now: datetime | None = None,
    enforced_deadline: datetime | None = None,
) -> RangeLease:
    """Return the product-authoritative lease for a new range generation."""
    current = now or timezone.now()
    if range_source is RangeSource.CTF:
        if enforced_deadline is None or enforced_deadline <= current:
            raise RangeLeaseConflict("CTF range cleanup deadline must be in the future")
        return RangeLease(enforced_deadline, enforced_deadline, 0)
    if range_source is not RangeSource.MISSION_CONTROL:
        raise RangeLeaseConflict("Unsupported range source")
    return RangeLease(
        current + timedelta(days=MISSION_CONTROL_INITIAL_DAYS),
        current + timedelta(days=MISSION_CONTROL_MAXIMUM_DAYS),
        MISSION_CONTROL_EXTENSION_DAYS,
    )


def _projection(instance: RangeInstance) -> RangeLeaseProjection:
    """Build a lease projection from a fully leased range instance."""
    if instance.expires_at is None or instance.maximum_expires_at is None:
        raise RangeLeaseConflict("Range lease is unavailable")
    can_extend = (
        instance.range_source == RangeSource.MISSION_CONTROL.value
        and instance.status
        not in {ResourceStatus.DESTROYING.value, ResourceStatus.DESTROYED.value, ResourceStatus.FAILED.value}
        and instance.expires_at > timezone.now()
        and instance.expires_at < instance.maximum_expires_at
    )
    return RangeLeaseProjection(
        expires_at=instance.expires_at,
        maximum_expires_at=instance.maximum_expires_at,
        extension_days=MISSION_CONTROL_EXTENSION_DAYS,
        can_extend=can_extend,
    )


def get_range_lease_projection(instance: RangeInstance) -> RangeLeaseProjection | None:
    """Return the safe lease projection, or None for a legacy unleased row."""
    if instance.expires_at is None or instance.maximum_expires_at is None:
        return None
    return _projection(instance)


def get_mission_control_range_lease(user: User) -> RangeLeaseProjection | None:
    """Return the caller's active Mission Control lease projection."""
    if getattr(user, "id", None) is None:
        return None
    instance = (
        RangeInstance.objects.filter(user_id=user.id, range_source=RangeSource.MISSION_CONTROL.value)
        .exclude(status=ResourceStatus.DESTROYING.value)
        .first()
    )
    return get_range_lease_projection(instance) if instance is not None else None


def extend_mission_control_range(user: User) -> RangeLeaseProjection:
    """Advance the caller's active Mission Control lease by one bounded increment."""
    if getattr(user, "id", None) is None:
        raise RangeLeaseNotFound("Range not found")
    with transaction.atomic():
        instance = (
            RangeInstance.objects.select_for_update()
            .filter(user_id=user.id, range_source=RangeSource.MISSION_CONTROL.value)
            .exclude(
                status__in=(
                    ResourceStatus.DESTROYING.value,
                    ResourceStatus.DESTROYED.value,
                    ResourceStatus.FAILED.value,
                )
            )
            .first()
        )
        if instance is None:
            raise RangeLeaseNotFound("Range not found")
        if instance.expires_at is None or instance.maximum_expires_at is None:
            raise RangeLeaseConflict("Range lease is unavailable")
        if instance.expires_at <= timezone.now():
            raise RangeLeaseConflict("Range lease has expired")
        if instance.expires_at >= instance.maximum_expires_at:
            raise RangeLeaseConflict("Range has reached its maximum lifetime")
        previous = instance.expires_at
        instance.expires_at = min(
            instance.expires_at + timedelta(days=MISSION_CONTROL_EXTENSION_DAYS),
            instance.maximum_expires_at,
        )
        instance.save(update_fields=["expires_at", "updated_at"])
        from cms import services as cms_services

        cms_services.audit_log(
            AuditEvent(
                entity_type=AuditEntityType.RANGE,
                entity_id=instance.pk,
                action=AuditAction.UPDATE,
                actor_type=AuditActorType.USER,
                actor_id=user.id,
                previous_state={"expires_at": previous.isoformat()},
                new_state={"expires_at": instance.expires_at.isoformat()},
                request_id=str(instance.request.request_id) if instance.request else "",
                context="mission_control_range_lease_extension",
            )
        )
        return _projection(instance)


def reconcile_ctf_range_leases(range_instance_ids: Iterable[int], enforced_deadline: datetime) -> int:
    """Move active CTF cleanup deadlines without exceeding credential ceilings.

    Event rescheduling may shorten a generation's lease or move it later up to
    the immutable ``maximum_expires_at`` used when its VPN credential was
    issued.  Moving beyond that ceiling requires a new generation and is
    rejected before any row is changed.
    """
    instance_ids = sorted({instance_id for instance_id in range_instance_ids if instance_id > 0})
    if not instance_ids:
        return 0
    with transaction.atomic():
        instances = list(
            RangeInstance.objects.select_for_update()
            .filter(pk__in=instance_ids, range_source=RangeSource.CTF.value)
            .exclude(status=ResourceStatus.DESTROYING.value)
        )
        for instance in instances:
            if instance.expires_at is None or instance.maximum_expires_at is None:
                raise RangeLeaseConflict("CTF range lease is unavailable")
            if enforced_deadline > instance.maximum_expires_at:
                raise RangeLeaseConflict("CTF cleanup deadline exceeds the range generation lifetime")
        changed_ids = [instance.pk for instance in instances if instance.expires_at != enforced_deadline]
        if changed_ids:
            RangeInstance.objects.filter(pk__in=changed_ids).update(
                expires_at=enforced_deadline,
                updated_at=timezone.now(),
            )
        return len(changed_ids)


def _dispatch_expired_range(instance: RangeInstance) -> None:
    """Use the canonical system-attributed destroy boundary for one due range."""
    from cms.services._range_destroy import destroy_expired_range

    destroy_expired_range(instance)


def expire_due_ranges(*, now: datetime | None = None, batch_size: int = 100) -> dict[str, int]:
    """Claim and dispatch a bounded batch of due live ranges."""
    current = now or timezone.now()
    due_ids = list(
        RangeInstance.objects.filter(expires_at__lte=current)
        .exclude(
            status__in=(ResourceStatus.DESTROYING.value, ResourceStatus.DESTROYED.value, ResourceStatus.FAILED.value)
        )
        .order_by("expires_at")
        .values_list("pk", flat=True)[:batch_size]
    )
    counts = {"expired": 0, "failed": 0}
    for instance_id in due_ids:
        try:
            with transaction.atomic():
                instance = (
                    RangeInstance.objects.select_for_update(skip_locked=True)
                    .filter(pk=instance_id, expires_at__lte=current)
                    .exclude(
                        status__in=(
                            ResourceStatus.DESTROYING.value,
                            ResourceStatus.DESTROYED.value,
                            ResourceStatus.FAILED.value,
                        )
                    )
                    .first()
                )
                if instance is None:
                    continue
                _dispatch_expired_range(instance)
            counts["expired"] += 1
        except Exception:
            counts["failed"] += 1
            logger.exception("Range lease cleanup failed for range_instance=%s", safe_log_id(instance_id))
    return counts
