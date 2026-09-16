"""Read-only admission queries for authoritative operation-result apply."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from engine.models import OperationResultInbox


def discriminator_mismatch(row: OperationResultInbox, envelope: dict[str, Any]) -> str:
    """Return a reason when a flattened inbox column disagrees with the envelope."""
    for field in ("operation_id", "request_id", "resource", "operation", "contract_version"):
        if str(getattr(row, field)) != str(envelope[field]):
            return f"inbox {field} does not match the envelope"
    return ""


def has_conflicting_sibling(row: OperationResultInbox) -> bool:
    """Return whether this step has another row with a different payload."""
    from engine.models import OperationResultInbox as Inbox

    digests = (
        Inbox.objects.filter(operation_id=row.operation_id, result_step=row.result_step)
        .values_list("payload_digest", flat=True)
        .distinct()
    )
    return len(set(digests)) > 1


def applied_steps(row: OperationResultInbox) -> list[str]:
    """Return the steps already applied for this operation generation."""
    from engine.models import OperationResultDisposition
    from engine.models import OperationResultInbox as Inbox

    return list(
        Inbox.objects.filter(
            operation_id=row.operation_id,
            disposition=OperationResultDisposition.APPLIED,
        )
        .exclude(result_step="")
        .values_list("result_step", flat=True)
    )


def has_earlier_pending_sibling(row: OperationResultInbox) -> bool:
    """Return whether an earlier-created result of this generation is pending."""
    from engine.models import OperationResultDisposition
    from engine.models import OperationResultInbox as Inbox

    return (
        Inbox.objects.filter(
            operation_id=row.operation_id,
            disposition=OperationResultDisposition.PENDING,
            created_at__lt=row.created_at,
        )
        .exclude(pk=row.pk)
        .exists()
    )
