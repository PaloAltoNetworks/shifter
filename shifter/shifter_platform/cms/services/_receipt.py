"""CMS-authoritative projection of CTF participant receipt bindings."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.db import transaction
from django.utils import timezone

from cms.exceptions import CMSError
from cms.models import RangeInstance
from engine.services import ReceiptBindingUnavailable
from shared.enums import RangeSource, ResourceStatus

_BINDING_UNAVAILABLE = "CTF receipt range binding is unavailable"

if TYPE_CHECKING:
    from uuid import UUID

    from shared.receipt_validation import ReceiptVerifierBinding


class ReceiptRangeBindingUnavailable(CMSError):
    """The named CMS range cannot authorize receipt validation."""


def project_ctf_receipt_binding(
    range_instance_pk: int,
    *,
    owner_user_id: int,
    event_id: UUID,
    participant_id: UUID,
    profile_id: str,
    objective_id: str,
) -> ReceiptVerifierBinding:
    """Project one exact live CTF assignment through CMS and Engine authority."""
    if isinstance(range_instance_pk, bool) or not isinstance(range_instance_pk, int) or range_instance_pk <= 0:
        raise ReceiptRangeBindingUnavailable(_BINDING_UNAVAILABLE)

    instance = RangeInstance.objects.select_related("request").filter(pk=range_instance_pk).first()
    if instance is None or not _cms_binding_is_usable(instance, owner_user_id):
        raise ReceiptRangeBindingUnavailable(_BINDING_UNAVAILABLE)

    request = instance.request
    if request is None:
        raise ReceiptRangeBindingUnavailable(_BINDING_UNAVAILABLE)
    from cms import services as cms_services

    try:
        return cms_services.engine_project_receipt_verifier_binding(
            request.request_id,
            owner_user_id=owner_user_id,
            event_id=event_id,
            participant_id=participant_id,
            profile_id=profile_id,
            objective_id=objective_id,
        )
    except ReceiptBindingUnavailable as exc:
        raise ReceiptRangeBindingUnavailable(_BINDING_UNAVAILABLE) from exc


@transaction.atomic
def confirm_ctf_receipt_binding(
    range_instance_pk: int,
    *,
    owner_user_id: int,
    objective_id: str,
    expected: ReceiptVerifierBinding,
) -> None:
    """Lock CMS/Engine assignment state and confirm the callback's exact binding."""
    # Lock only the RangeInstance row.  ``request`` is nullable, so PostgreSQL
    # rejects a broad FOR UPDATE over the outer join introduced by select_related.
    instance = (
        RangeInstance.objects.select_for_update(of=("self",))
        .select_related("request")
        .filter(pk=range_instance_pk)
        .first()
    )
    if instance is None or not _cms_binding_is_usable(instance, owner_user_id) or instance.request is None:
        raise ReceiptRangeBindingUnavailable("CTF receipt range binding is no longer active")
    from cms import services as cms_services

    try:
        cms_services.engine_confirm_receipt_verifier_binding(
            instance.request.request_id,
            owner_user_id=owner_user_id,
            objective_id=objective_id,
            expected=expected,
        )
    except ReceiptBindingUnavailable as exc:
        raise ReceiptRangeBindingUnavailable("CTF receipt range binding is no longer active") from exc


def _cms_binding_is_usable(instance: RangeInstance, owner_user_id: int) -> bool:
    """Check the CMS-owned provenance, owner, lifecycle, scope, and lease facts."""
    request = instance.request
    return bool(
        request is not None
        and instance.range_source == RangeSource.CTF.value
        and instance.user_id == owner_user_id
        and request.user_id == owner_user_id
        and instance.workspace_id == request.workspace_id
        and instance.status == ResourceStatus.READY.value
        and instance.expires_at is not None
        and instance.expires_at > timezone.now()
    )
