"""CTF signal receivers for CMS events.

Connects to CMS signals to keep CTF data in sync with range status changes.
"""

from __future__ import annotations

import logging
from typing import Literal

from django.db import connection
from django.db.models import Model
from django.db.models.signals import post_save, pre_delete, pre_save
from django.dispatch import receiver

from cms.services import range_status_changed
from shared.enums import ResourceStatus
from shared.model_access import OwnedReference

logger = logging.getLogger(__name__)


def _authority_ref(noun: str, value: object) -> OwnedReference | None:
    """Build a qualified CTF authority reference when an identifier exists."""
    if value is None:
        return None
    return OwnedReference(owner="ctf", reference=f"{noun}:{value}")


def _invalidate_model_access(
    references: list[OwnedReference | None],
    reason: str,
    *,
    allocation_effect: Literal["revoke", "selector_only"] = "revoke",
) -> None:
    """Invalidate the unique non-null authority references in stable order."""
    from ctf.bridges import cms_invalidate_model_access_authority
    from shared.model_access import AuthorityInvalidation, AuthorityState

    unique = {(reference.owner, reference.reference): reference for reference in references if reference is not None}
    if not unique:
        return
    cms_invalidate_model_access_authority(
        AuthorityInvalidation(
            deployment_id=None,
            authority_refs=tuple(unique[key] for key in sorted(unique)),
            state=AuthorityState.UNKNOWN,
            reason=reason,
            allocation_effect=allocation_effect,
        )
    )


def _capture_authority_fields(sender: type[Model], instance: Model, fields: tuple[str, ...]) -> None:
    """Capture persisted authority fields before a model mutation."""
    if instance._state.adding:
        instance._model_access_authority_before = None  # type: ignore[attr-defined]
        return
    persisted = sender.all_objects.filter(pk=instance.pk).values(*fields).first()  # type: ignore[attr-defined]
    instance._model_access_authority_before = persisted  # type: ignore[attr-defined]


def _changed(instance: Model, fields: tuple[str, ...]) -> bool:
    """Return whether any captured authority field changed."""
    before = getattr(instance, "_model_access_authority_before", None)
    return before is None or any(before[field] != getattr(instance, field) for field in fields)


from ctf.models import (  # noqa: E402 - Django signal senders are imported after setup
    CTFCohort,
    CTFEvent,
    CTFEventStaff,
    CTFParticipant,
    CTFSpareRange,
    CTFTeam,
)

_PARTICIPANT_AUTHORITY_FIELDS = (
    "event_id",
    "team_id",
    "cohort_id",
    "range_instance_id",
    "status",
    "registered_at",
    "deleted_at",
)
_SPARE_AUTHORITY_FIELDS = (
    "event_id",
    "team_id",
    "cohort_id",
    "range_instance_id",
    "status",
    "deleted_at",
)
_EVENT_AUTHORITY_FIELDS = (
    "created_by_id",
    "status",
    "deleted_at",
    "model_demand",
    "event_start",
    "event_end",
    "range_spinup_minutes",
    "cleanup_delay_hours",
)


@receiver(pre_save, sender=CTFParticipant, dispatch_uid="ctf.model_access.participant.capture")
def capture_participant_model_access(sender: type[CTFParticipant], instance: CTFParticipant, **kwargs: object) -> None:
    """Capture participant authority before saving."""
    _capture_authority_fields(sender, instance, _PARTICIPANT_AUTHORITY_FIELDS)


@receiver(post_save, sender=CTFParticipant, dispatch_uid="ctf.model_access.participant.invalidate")
def invalidate_participant_model_access(
    sender: type[CTFParticipant], instance: CTFParticipant, **kwargs: object
) -> None:
    """Invalidate participant selectors after an authority change."""
    if not _changed(instance, _PARTICIPANT_AUTHORITY_FIELDS):
        return
    before = getattr(instance, "_model_access_authority_before", None) or {}
    changed = {field for field in _PARTICIPANT_AUTHORITY_FIELDS if before.get(field) != getattr(instance, field)}
    if changed == {"range_instance_id"}:
        # Realizing the participant's range changes selector membership from the
        # stable draw to the canonical range reference. It does not revoke the
        # already-admitted launch generation or the participant's eligibility.
        _invalidate_model_access(
            [
                _authority_ref("event", instance.event_id),
                _authority_ref("team", instance.team_id),
                _authority_ref("cohort", instance.cohort_id),
            ],
            "ctf-participant-range-realized",
            allocation_effect="selector_only",
        )
        return
    _invalidate_model_access(
        [
            _authority_ref("participant", instance.pk),
            _authority_ref("event", before.get("event_id")),
            _authority_ref("event", instance.event_id),
            _authority_ref("team", before.get("team_id")),
            _authority_ref("team", instance.team_id),
            _authority_ref("cohort", before.get("cohort_id")),
            _authority_ref("cohort", instance.cohort_id),
        ],
        "ctf-participant-changed",
    )


@receiver(pre_save, sender=CTFSpareRange, dispatch_uid="ctf.model_access.spare.capture")
def capture_spare_model_access(sender: type[CTFSpareRange], instance: CTFSpareRange, **kwargs: object) -> None:
    """Capture spare-range authority before saving."""
    _capture_authority_fields(sender, instance, _SPARE_AUTHORITY_FIELDS)


@receiver(post_save, sender=CTFSpareRange, dispatch_uid="ctf.model_access.spare.invalidate")
def invalidate_spare_model_access(sender: type[CTFSpareRange], instance: CTFSpareRange, **kwargs: object) -> None:
    """Invalidate spare-range selectors after an authority change."""
    if not _changed(instance, _SPARE_AUTHORITY_FIELDS):
        return
    before = getattr(instance, "_model_access_authority_before", None) or {}
    _invalidate_model_access(
        [
            _authority_ref("spare", instance.pk),
            _authority_ref("event", before.get("event_id")),
            _authority_ref("event", instance.event_id),
            _authority_ref("team", before.get("team_id")),
            _authority_ref("team", instance.team_id),
            _authority_ref("cohort", before.get("cohort_id")),
            _authority_ref("cohort", instance.cohort_id),
        ],
        "ctf-spare-changed",
    )


def _capture_container(sender: type[Model], instance: Model, **kwargs: object) -> None:
    """Capture team or cohort authority before saving."""
    _capture_authority_fields(sender, instance, ("event_id", "deleted_at"))


def _invalidate_container(noun: str, instance: Model) -> None:
    """Invalidate a team or cohort and its enclosing event when changed."""
    if not _changed(instance, ("event_id", "deleted_at")):
        return
    before = getattr(instance, "_model_access_authority_before", None) or {}
    _invalidate_model_access(
        [
            _authority_ref(noun, instance.pk),
            _authority_ref("event", before.get("event_id")),
            _authority_ref("event", getattr(instance, "event_id", None)),
        ],
        f"ctf-{noun}-changed",
    )


@receiver(pre_save, sender=CTFTeam, dispatch_uid="ctf.model_access.team.capture")
@receiver(pre_save, sender=CTFCohort, dispatch_uid="ctf.model_access.cohort.capture")
def capture_model_access_container(sender: type[Model], instance: Model, **kwargs: object) -> None:
    """Capture a team or cohort authority snapshot before saving."""
    _capture_container(sender, instance)


@receiver(post_save, sender=CTFTeam, dispatch_uid="ctf.model_access.team.invalidate")
@receiver(pre_delete, sender=CTFTeam, dispatch_uid="ctf.model_access.team.delete")
def invalidate_team_model_access(sender: type[CTFTeam], instance: CTFTeam, **kwargs: object) -> None:
    """Invalidate team authority after update or before deletion."""
    _invalidate_container("team", instance)


@receiver(post_save, sender=CTFCohort, dispatch_uid="ctf.model_access.cohort.invalidate")
@receiver(pre_delete, sender=CTFCohort, dispatch_uid="ctf.model_access.cohort.delete")
def invalidate_cohort_model_access(sender: type[CTFCohort], instance: CTFCohort, **kwargs: object) -> None:
    """Invalidate cohort authority after update or before deletion."""
    _invalidate_container("cohort", instance)


@receiver(pre_save, sender=CTFEvent, dispatch_uid="ctf.model_access.event.capture")
def capture_event_model_access(sender: type[CTFEvent], instance: CTFEvent, **kwargs: object) -> None:
    """Capture event authority before saving."""
    _capture_authority_fields(sender, instance, _EVENT_AUTHORITY_FIELDS)


@receiver(post_save, sender=CTFEvent, dispatch_uid="ctf.model_access.event.invalidate")
@receiver(pre_delete, sender=CTFEvent, dispatch_uid="ctf.model_access.event.delete")
def invalidate_event_model_access(sender: type[CTFEvent], instance: CTFEvent, **kwargs: object) -> None:
    """Invalidate an event selector after authority changes or deletion."""
    if _changed(instance, _EVENT_AUTHORITY_FIELDS):
        _invalidate_model_access(
            [_authority_ref("event", instance.pk), _authority_ref("event-launch", instance.pk)],
            "ctf-event-changed",
        )


@receiver(post_save, sender=CTFEventStaff, dispatch_uid="ctf.model_access.staff.invalidate")
@receiver(pre_delete, sender=CTFEventStaff, dispatch_uid="ctf.model_access.staff.delete")
def invalidate_event_staff_model_access(sender: type[CTFEventStaff], instance: CTFEventStaff, **kwargs: object) -> None:
    """Invalidate event authority after staff membership changes."""
    if connection.in_atomic_block:
        tuple(CTFEvent.objects.select_for_update().filter(pk=instance.event_id))
    _invalidate_model_access(
        [_authority_ref("event", instance.event_id)],
        "ctf-event-staff-changed",
    )


@receiver(pre_save, sender=CTFEventStaff, dispatch_uid="ctf.model_access.staff.lock")
def lock_event_for_staff_model_access(sender: type[CTFEventStaff], instance: CTFEventStaff, **kwargs: object) -> None:
    """Lock the owning event before staff authority mutation."""
    if connection.in_atomic_block:
        tuple(CTFEvent.objects.select_for_update().filter(pk=instance.event_id))


@receiver(pre_delete, sender=CTFParticipant, dispatch_uid="ctf.model_access.participant.delete")
def invalidate_deleted_participant_model_access(
    sender: type[CTFParticipant], instance: CTFParticipant, **kwargs: object
) -> None:
    """Invalidate every selector affected by participant deletion."""
    _invalidate_model_access(
        [
            _authority_ref("participant", instance.pk),
            _authority_ref("event", instance.event_id),
            _authority_ref("team", instance.team_id),
            _authority_ref("cohort", instance.cohort_id),
        ],
        "ctf-participant-deleted",
    )


@receiver(pre_delete, sender=CTFSpareRange, dispatch_uid="ctf.model_access.spare.delete")
def invalidate_deleted_spare_model_access(
    sender: type[CTFSpareRange], instance: CTFSpareRange, **kwargs: object
) -> None:
    """Invalidate every selector affected by spare-range deletion."""
    _invalidate_model_access(
        [
            _authority_ref("spare", instance.pk),
            _authority_ref("event", instance.event_id),
            _authority_ref("team", instance.team_id),
            _authority_ref("cohort", instance.cohort_id),
        ],
        "ctf-spare-deleted",
    )


@receiver(range_status_changed)
def sync_ctf_participant_range_status(
    sender: object,
    range_instance_id: int,
    new_status: str,
    previous_status: str,
    **kwargs: object,
) -> None:
    """Update CTFParticipant.range_status when CMS reports a status change."""
    from ctf.models import CTFParticipant

    participants = CTFParticipant.objects.filter(
        range_instance_id=range_instance_id,
    )

    # Scoped provider inventory/readback evidence that every owned resource is
    # gone (#2086, ADR-063-R4/R5). A logical DESTROYED status alone is not proof
    # of absence, so capacity/linkage release waits for this.
    cleanup_verified = bool(kwargs.get("cleanup_verified", False))

    updated = 0
    for participant in participants:
        if new_status == ResourceStatus.DESTROYED.value and cleanup_verified:
            # Verified terminal cleanup: the range's resources are confirmed gone,
            # so return its capacity draw BEFORE dropping the linkage. Idempotent;
            # never raises.
            from ctf.services.range.capacity import release_range

            release_range(participant.pk)
            participant.range_instance_id = None
            participant.range_status = ""
            participant.save(update_fields=["range_instance_id", "range_status", "updated_at"])
            updated += 1
        elif participant.range_status != new_status:
            # Any non-verified status -- including DESTROYED without inventory
            # evidence -- retains the participant/range/reservation linkage and
            # capacity until inventory confirms absence (#1919, ADR-063-R5).
            participant.range_status = new_status
            participant.save(update_fields=["range_status", "updated_at"])
            updated += 1

    if updated:
        logger.info(
            "Synced range_status=%s for %d CTF participant(s) (range_instance_id=%s, was=%s)",
            new_status,
            updated,
            range_instance_id,
            previous_status,
        )


@receiver(range_status_changed)
def sync_ctf_spare_range_status(
    sender: None,
    range_instance_id: int,
    new_status: str,
    previous_status: str,
    **kwargs: object,
) -> None:
    """Update CTFSpareRange.status when CMS reports a status change (#1018).

    This is the "existing event projection" that a spare's status uses to
    reach ``ready``/``failed`` -- no separate polling loop is introduced for
    the spare pool. Only unconsumed spares are touched: once a spare is
    consumed, its range belongs to the participant and further status
    changes are the participant-range projection's concern
    (:func:`sync_ctf_participant_range_status`), not the pool's.
    """
    from ctf.enums import SpareRangeStatus
    from ctf.models import CTFSpareRange

    status_map = {
        ResourceStatus.READY.value: SpareRangeStatus.READY.value,
        ResourceStatus.FAILED.value: SpareRangeStatus.FAILED.value,
        ResourceStatus.DESTROYED.value: SpareRangeStatus.FAILED.value,
    }
    mapped_status = status_map.get(new_status)
    if mapped_status is None:
        return

    spares = CTFSpareRange.objects.filter(
        range_instance_id=range_instance_id,
        consumed_by__isnull=True,
    )

    updated = 0
    for spare in spares:
        if spare.status != mapped_status:
            spare.status = mapped_status
            terminal = new_status in {ResourceStatus.FAILED.value, ResourceStatus.DESTROYED.value}
            owner = spare.owner_user if terminal else None
            if terminal:
                spare.owner_user = None
                spare.save(update_fields=["status", "owner_user", "updated_at"])
                from ctf.services.range.spares import delete_managed_spare_user

                delete_managed_spare_user(owner)
            else:
                spare.save(update_fields=["status", "updated_at"])
            updated += 1

    if updated:
        logger.info(
            "Synced spare status=%s for %d CTF spare range(s) (range_instance_id=%s, was=%s)",
            mapped_status,
            updated,
            range_instance_id,
            previous_status,
        )
