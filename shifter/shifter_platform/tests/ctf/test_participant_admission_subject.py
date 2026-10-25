"""Authoritative participant membership subject for model admission (PLAT-202, #2119).

A replacement launch must resolve the realized range reference (matching the
published #2139/#2140 membership) rather than always the draw reference, so a
range-scoped sharing restriction cannot be bypassed by rebuild/reprovision. The
realized range resolves in any lifecycle state, so a FAILED range hands its
identity to its replacement (#2462). Real CMS/Engine rows, no first-party mocks.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from django.utils import timezone

from cms.exceptions import CMSError
from cms.models import RangeInstance
from cms.models import Request as CmsRequest
from ctf.models import CTFParticipant
from ctf.services.model_access_sharing import participant_model_admission_subject
from engine.models import Range as EngineRange
from engine.models import Request as EngineRequest
from shared.enums import RangeSource, RequestType, ResourceStatus
from shared.model_access import OwnedReference

pytestmark = pytest.mark.django_db


def _participant(event, *, range_instance_id=None):
    return CTFParticipant.objects.create(
        event=event,
        email=f"p-{uuid4().hex[:8]}@test.com",
        name="p",
        status="active",
        registered_at=timezone.now(),
        range_instance_id=range_instance_id,
    )


def _realized_range(owner, *, engine_status, cms_status) -> tuple[RangeInstance, EngineRange]:
    """Create a CTF range instance and the Engine range realized for its request."""
    from workspaces.services import resolve_personal_workspace

    workspace_id = resolve_personal_workspace(owner).workspace_id
    cms_request = CmsRequest.objects.create(
        workspace_id=workspace_id, request_id=uuid4(), request_type=RequestType.RANGE.value, user=owner
    )
    engine_request = EngineRequest.objects.create(
        request_id=cms_request.request_id, request_type=RequestType.RANGE.value, user=owner
    )
    engine_range = EngineRange.objects.create(
        workspace_id=workspace_id, user=owner, request=engine_request, cms_user_id=owner.id, status=engine_status
    )
    range_instance = RangeInstance.objects.create(
        workspace_id=workspace_id,
        request=cms_request,
        scenario_id="basic",
        user_id=owner.id,
        range_source=RangeSource.CTF.value,
        status=cms_status,
    )
    return range_instance, engine_range


def test_participant_without_range_uses_draw_reference(ctf_event):
    participant = _participant(ctf_event)
    subject = participant_model_admission_subject(participant)
    assert subject == OwnedReference(owner="ctf", reference=f"draw:{participant.pk}")


@pytest.mark.parametrize(
    ("engine_status", "cms_status"),
    [
        (EngineRange.Status.READY, ResourceStatus.READY.value),
        (EngineRange.Status.DESTROYING, ResourceStatus.DESTROYING.value),
        # A terminal status soft-deletes the CMS instance (#2462).
        (EngineRange.Status.FAILED, ResourceStatus.FAILED.value),
        (EngineRange.Status.DESTROYED, ResourceStatus.DESTROYED.value),
    ],
)
def test_realized_range_resolves_its_range_reference_in_any_state(
    ctf_event, participant_user, engine_status, cms_status
):
    range_instance, engine_range = _realized_range(participant_user, engine_status=engine_status, cms_status=cms_status)
    participant = _participant(ctf_event, range_instance_id=range_instance.pk)

    assert participant_model_admission_subject(participant) == OwnedReference(
        owner="deployment", reference=f"range:{engine_range.uuid}"
    )


def test_unresolvable_realized_range_fails_closed(ctf_event, participant_user):
    # A realized range that cannot be resolved fails closed (raises) rather than
    # substituting the draw identity, which would drop a published range-scoped
    # restriction: an unknown instance, an instance whose request never realized an
    # Engine range, and a request with an ambiguous Engine range all refuse.
    unknown = _participant(ctf_event, range_instance_id=987654)
    unrealized, engine_range = _realized_range(
        participant_user, engine_status=EngineRange.Status.FAILED, cms_status=ResourceStatus.FAILED.value
    )
    engine_range.delete()
    ambiguous, duplicate = _realized_range(
        participant_user, engine_status=EngineRange.Status.FAILED, cms_status=ResourceStatus.FAILED.value
    )
    EngineRange.objects.create(
        workspace_id=duplicate.workspace_id,
        user=participant_user,
        request=duplicate.request,
        status=EngineRange.Status.READY,
    )

    for participant in (
        unknown,
        _participant(ctf_event, range_instance_id=unrealized.pk),
        _participant(ctf_event, range_instance_id=ambiguous.pk),
    ):
        with pytest.raises(CMSError, match="Model-access selector denied"):
            participant_model_admission_subject(participant)
