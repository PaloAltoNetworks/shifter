"""Maintenance-only, bounded transfer from retired notification writers.

The operator must stop old web/scheduler processes and drain email threads before
installing the fence. Database locks cannot recall an already dispatched email.
Email declarations remain staged without runnable work until an adapter exists.
"""

from __future__ import annotations

from uuid import UUID

from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone

import workspaces.services as ws
from ctf.exceptions import CTFCommunicationError
from ctf.models import (
    CommunicationCampaign,
    CommunicationCutover,
    CommunicationIntent,
    CTFEvent,
    CTFNotification,
    CTFScheduledTask,
    LegacyCommunication,
)
from ctf.services.communication import AdmissionActor, CampaignDraft, create_campaign, schedule_declaration
from ctf.services.communication.adapters import registered_channels


def _blocked() -> CTFCommunicationError:
    """Build a bounded diagnostic requiring operator reconciliation."""

    return CTFCommunicationError("Legacy cutover requires reconciliation", code="CTF_COMMUNICATION_CUTOVER_BLOCKED")


def _assert_quiescent() -> None:
    """Reject unresolved sends or claimed tasks before transferring ownership."""

    if (
        CTFNotification.all_objects.filter(status="sending").exists()
        or CTFScheduledTask.all_objects.filter(status="running").exists()
    ):
        raise _blocked()


def start_cutover(*, legacy_producers_stopped: bool = False) -> CommunicationCutover:
    """Record the operator's quiescence assertion and install durable writer fencing."""
    if not legacy_producers_stopped:
        raise _blocked()
    with transaction.atomic():
        # Also serialize with legacy INSERT/UPDATE transactions already in flight.
        if connection.vendor == "postgresql":
            with connection.cursor() as cursor:
                cursor.execute("LOCK TABLE ctf_notification, ctf_scheduled_task IN SHARE ROW EXCLUSIVE MODE")
        _assert_quiescent()
        return CommunicationCutover.objects.get_or_create(pk=1, defaults={"fenced_at": timezone.now()})[0]


def _draft(row: CTFNotification) -> CommunicationCampaign:
    """Convert a valid legacy declaration without changing its channel or author."""

    if (
        row.notification_type != "announcement"
        or row.recipient_filter not in {"participants", "all"}
        or row.recipient_emails
        or row.event.deleted_at
        or row.deleted_at
    ):
        raise _blocked()
    if row.status not in {"draft", "scheduled"}:
        raise _blocked()
    if (row.status == "scheduled") != (row.scheduled_at is not None):
        raise _blocked()
    try:
        binding = ws.authorize_bound_workspace(
            row.created_by, row.event.workspace_id, ws.WorkspaceOperation.USE_CTF_COMMUNICATIONS
        )
    except ws.WorkspaceAuthorizationError:
        raise _blocked() from None
    trigger = (
        {"kind": "manual"}
        if row.scheduled_at is None
        else {"kind": "absolute_time", "due_at": row.scheduled_at.isoformat()}
    )
    return create_campaign(
        row.created_by,
        binding.workspace_uuid,
        CampaignDraft(
            title=row.subject,
            origin="organizer_staff",
            target_event_ids=[row.event_id],
            audience_spec={"kind": "event", "event_ids": [str(row.event_id)]},
            trigger_spec=trigger,
            channels=["email"],
            subject=row.subject,
            body=row.body,
        ),
        maintenance=True,
    )


def _validate_pending_task_ownership(row: CTFNotification, tasks: list[CTFScheduledTask]) -> None:
    """Require one matching scheduled task or no task for an unpublished draft."""
    if row.status == "scheduled" and (len(tasks) != 1 or tasks[0].scheduled_for != row.scheduled_at):
        raise _blocked()
    if row.status == "draft" and tasks:
        raise _blocked()


def _migrate_row(row: CTFNotification) -> None:
    """Transfer one declaration and cancel its old tasks under the batch transaction."""
    # Match the event-first lock order used by admission and deletion.
    CTFEvent.all_objects.select_for_update().get(pk=row.event_id)
    row = CTFNotification.all_objects.select_for_update().select_related("event", "created_by").get(pk=row.pk)
    tasks = list(
        CTFScheduledTask.all_objects.select_for_update().filter(
            task_type__in=["send_notification", "send_reminder"],
            metadata__notification_id=str(row.pk),
            status__in=["pending", "running"],
        )
    )
    if any(task.status == "running" or task.event_id != row.event_id for task in tasks):
        raise _blocked()
    if row.status in {"sent", "failed"}:
        if tasks:
            raise _blocked()
        LegacyCommunication.objects.create(legacy=row, disposition="historical")
        return
    _validate_pending_task_ownership(row, tasks)
    campaign = _draft(row)
    LegacyCommunication.objects.create(
        legacy=row,
        campaign=campaign,
        disposition="channel_unavailable" if "email" not in registered_channels() else "staged",
    )
    for task in tasks:
        task.cancel_if_active()


def migrate_legacy_batch(*, batch_size: int = 100) -> int:
    """Transfer a bounded batch atomically; retries skip committed mappings."""
    if not 1 <= batch_size <= 500:
        raise _blocked()
    with transaction.atomic():
        if not CommunicationCutover.objects.select_for_update().filter(pk=1).exists():
            raise _blocked()
        _assert_quiescent()
        rows = list(CTFNotification.all_objects.filter(ledger_mapping__isnull=True).order_by("pk")[:batch_size])
        for row in rows:
            _migrate_row(row)
        return len(rows)


def activate_cutover() -> dict[str, bool | int]:
    """Activate only after every legacy row/task has an explicit disposition.

    Missing email transport stays a durable, visible dependency; it creates no
    runnable task or delivery command. Dependency recovery explicitly resumes
    individual mapped schedules through the existing idempotent service.
    """
    with transaction.atomic():
        fence = CommunicationCutover.objects.select_for_update().filter(pk=1).first()
        if fence is None or CTFNotification.all_objects.filter(ledger_mapping__isnull=True).exists():
            raise _blocked()
        _assert_quiescent()
        if CTFScheduledTask.all_objects.filter(
            Q(task_type="send_notification") | Q(task_type="send_reminder", metadata__has_key="notification_id"),
            status__in=["pending", "running"],
        ).exists():
            raise _blocked()
        fence.activated_at = fence.activated_at or timezone.now()
        fence.save(update_fields=["activated_at"])
        return {
            "active": True,
            "email_ready": "email" in registered_channels(),
            "channel_unavailable": LegacyCommunication.objects.filter(disposition="channel_unavailable").count(),
        }


def resume_migrated_schedule(mapping_id: UUID) -> CommunicationIntent:
    """Explicit, bounded dependency recovery; never revive the legacy sender."""
    with transaction.atomic():
        mapping = LegacyCommunication.objects.select_related("campaign", "legacy").get(pk=mapping_id)
        if not CommunicationCutover.objects.filter(pk=1, activated_at__isnull=False).exists():
            raise _blocked()
        campaign = mapping.campaign
        if "email" not in registered_channels() or campaign is None or mapping.legacy.scheduled_at is None:
            raise _blocked()
        intent = schedule_declaration(
            campaign,
            due_at=mapping.legacy.scheduled_at,
            occurrence_key=f"legacy:{mapping.pk}",
            actor=AdmissionActor(user_id=mapping.legacy.created_by_id),
        )
        LegacyCommunication.objects.filter(pk=mapping.pk).update(disposition="transferred")
        return intent
