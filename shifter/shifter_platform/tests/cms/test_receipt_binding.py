"""CMS authority checks for participant-to-range receipt bindings."""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from cms.models import RangeInstance
from cms.models import Request as CmsRequest
from cms.services import ReceiptRangeBindingUnavailable, project_ctf_receipt_binding
from engine.models import Range
from engine.models import Request as EngineRequest
from engine.services import register_receipt_verifier
from shared.enums import RangeSource, RequestType, ResourceStatus
from shared.receipt_validation import ReceiptKeyMode, ReceiptRegistrationDemand

pytestmark = pytest.mark.django_db

_WORKSPACE_ID = 1


def _range_binding(*, source=RangeSource.CTF.value, status=ResourceStatus.READY.value):
    user = get_user_model().objects.create_user(username=f"receipt-cms-{uuid4()}@example.test")
    request_id = uuid4()
    cms_request = CmsRequest.objects.create(
        request_id=request_id,
        request_type=RequestType.RANGE.value,
        user=user,
        workspace_id=_WORKSPACE_ID,
    )
    engine_request = EngineRequest.objects.create(
        request_id=request_id,
        request_type=RequestType.RANGE.value,
        user=user,
    )
    engine_range = Range.objects.create(
        workspace_id=_WORKSPACE_ID,
        request=engine_request,
        user=user,
        cms_user_id=user.pk,
        status=Range.Status.READY,
        provisioner_operation="provision",
        provisioner_operation_id=request_id,
    )
    range_instance = RangeInstance.objects.create(
        request=cms_request,
        scenario_id="receipt-test",
        user_id=user.pk,
        workspace_id=_WORKSPACE_ID,
        status=status,
        range_source=source,
        expires_at=timezone.now() + timedelta(hours=1),
        maximum_expires_at=timezone.now() + timedelta(hours=1),
    )
    demand = ReceiptRegistrationDemand(
        deployment_id="gcp-dev",
        profile_id="keplerops-penr1",
        provider_contract="penr1-v1",
        ctf_event_id=uuid4(),
        ctf_participant_id=uuid4(),
        objectives=("flag-agent-control",),
        issuer_id="keplerops-proof",
        provider_range_namespace="range-355-a1",
        provider_participant_namespace="participant-01",
        key_mode=ReceiptKeyMode.REMOTE_SYMMETRIC,
        algorithm_id="hmac-sha256",
        key_id="range-key-v1",
        reset_generation=0,
        secret_version_ref="provider-secret-version-ref",
    )
    registered = register_receipt_verifier(request_id, request_id, demand)
    return user, range_instance, engine_range, demand, registered


def _project(user, range_instance, demand):
    return project_ctf_receipt_binding(
        range_instance.pk,
        owner_user_id=user.pk,
        event_id=demand.ctf_event_id,
        participant_id=demand.ctf_participant_id,
        profile_id=demand.profile_id,
        objective_id="flag-agent-control",
    )


def test_projects_exact_live_ctf_range_and_engine_registration():
    user, range_instance, engine_range, demand, registered = _range_binding()

    projected = _project(user, range_instance, demand)

    assert projected.registration_revision == registered.registration_revision
    assert projected.materialization_id == engine_range.uuid


@pytest.mark.parametrize(
    "mutation",
    [
        "wrong_source",
        "wrong_owner",
        "request_owner_drift",
        "not_ready",
        "expired",
        "soft_deleted",
        "workspace_drift",
    ],
)
def test_rejects_untrusted_or_unusable_cms_range_projection(mutation):
    user, range_instance, _engine_range, demand, _registered = _range_binding()
    if mutation == "wrong_source":
        range_instance.range_source = RangeSource.MISSION_CONTROL.value
        fields = ["range_source"]
    elif mutation == "wrong_owner":
        range_instance.user_id += 1
        fields = ["user_id"]
    elif mutation == "request_owner_drift":
        foreign = get_user_model().objects.create_user(username=f"receipt-cms-foreign-{uuid4()}@example.test")
        range_instance.request.user = foreign
        range_instance.request.save(update_fields=["user"])
        fields = []
    elif mutation == "not_ready":
        range_instance.status = ResourceStatus.PAUSED.value
        fields = ["status"]
    elif mutation == "expired":
        range_instance.expires_at = timezone.now() - timedelta(seconds=1)
        fields = ["expires_at"]
    elif mutation == "soft_deleted":
        range_instance.deleted_at = timezone.now()
        fields = ["deleted_at"]
    else:
        range_instance.workspace_id += 1
        fields = ["workspace_id"]
    if fields:
        range_instance.save(update_fields=fields)

    with pytest.raises(ReceiptRangeBindingUnavailable):
        _project(user, range_instance, demand)
