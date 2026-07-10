"""Engine-side creation + dispatch for the ACES-native provisioning path (ADR-031).

Parallel to :func:`engine.services.create_range` (the cyberscript path), but the
persisted truth is the serialized ACES ``ProvisioningPlan`` stored in
``mission_control_range.range_config`` (reused, no new table), realized by the
provisioner's ``aces-range`` command. The cyberscript ``create_range`` /
``interpret`` bodies are untouched (ADR-031-R2).

This module is reached only through the ACES dispatch port
(``cms.aces.dispatch``) which is constructed behind the
``SHIFTER_ACES_NATIVE_PROVISIONING`` flag; nothing here runs on the cyberscript
path.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from engine.ecs import start_aces_range_provisioning
from shared.enums import RequestType

__all__ = ["AcesRangeRef", "create_aces_range"]


@dataclass(frozen=True)
class AcesRangeRef:
    """IDs/status returned to the dispatch port after an ACES range is accepted."""

    request_id: str
    range_id: str
    status: str
    accepted: bool


def create_aces_range(*, request_id: str | UUID, user_id: int, compiled_plan: dict[str, Any]) -> AcesRangeRef:
    """Create + dispatch an ACES-native range from a serialized ACES plan.

    Persists an ``engine.models.Request`` and ``engine.models.Range`` (with
    ``range_config`` = the serialized ACES ProvisioningPlan, a plain dict that is
    self-describing via its ``kind``/``aces_sdl_version`` -- no cyberscript
    envelope and no Shifter-owned spec, ADR-031-R1 / ADR-032) keyed by
    ``request_id``, writes an ``operation_receipt`` sidecar, and dispatches the
    provisioner ``aces-range provision`` task. Idempotent on ``request_id``. On a
    dispatch failure the range is marked FAILED and the error re-raised, so a
    dispatch failure is never silent (mirrors ``create_range``).
    """
    # Imported lazily (like the cyberscript ``create_range`` path) so importing
    # the ``engine`` app does not define models before the app registry is ready.
    from engine.models import Range, Request

    request_uuid = request_id if isinstance(request_id, UUID) else UUID(str(request_id))

    existing = Range.objects.filter(request__request_id=request_uuid).first()
    if existing is not None:
        return AcesRangeRef(
            request_id=str(request_uuid), range_id=str(existing.uuid), status=existing.status, accepted=True
        )

    user_model = get_user_model()
    with transaction.atomic():
        user = user_model.objects.get(id=user_id)
        request = Request.objects.create(request_id=request_uuid, request_type=RequestType.RANGE.value, user=user)
        subnet_index = Range.allocate_subnet_index()
        range_obj = Range.objects.create(
            uuid=uuid4(),
            user=user,
            request=request,
            cms_user_id=user_id,
            status=Range.Status.PROVISIONING,
            subnet_index=subnet_index,
            range_config=compiled_plan,
        )
        _write_operation_receipt(request_uuid, range_id=str(range_obj.uuid))

    try:
        start_aces_range_provisioning(request_uuid)
    except Exception:
        range_obj.status = Range.Status.FAILED
        range_obj.error_message = "Provisioning dispatch failed"
        range_obj.save(update_fields=["status", "error_message", "updated_at"])
        raise

    return AcesRangeRef(
        request_id=str(request_uuid), range_id=str(range_obj.uuid), status=range_obj.status, accepted=True
    )


def _write_operation_receipt(request_id: UUID, *, range_id: str) -> None:
    """Write the idempotent operation_receipt sidecar for an accepted provision."""
    # Lazy import: shared.aces.operations pulls shared.models, which must not load
    # during app population (mirrors _aces_status.py).
    from shared.aces.operations import persist_operation_receipt_record

    operation_id = str(request_id)
    persist_operation_receipt_record(
        request_id=request_id,
        operation_id=operation_id,
        source_timestamp=timezone.now(),
        payload={"operation_id": operation_id, "accepted": True, "status": "accepted"},
        range_id=range_id,
    )
