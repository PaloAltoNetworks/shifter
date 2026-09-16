"""Warm activation authorization tests (#28).

Activation is authorized only for a *claimed* warm generation on a realized,
system-prepared (quarantined ``PROVISIONING``) range -- never for an arbitrary
range that merely happens to be READY. These tests pin both the dedicated
``warm_activation_authz`` gate and its delegation from the launch-intent
authorization path.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from engine.launch_intents import authorize_provisioner_payload
from engine.models import Range, Request, WarmRangeGeneration
from engine.warm_activation_authz import authorize_warm_activation

pytestmark = pytest.mark.django_db

_WORKSPACE_ID = 1


def _seed(*, range_status=Range.Status.PROVISIONING, with_claimed_generation=True):
    request_id = uuid4()
    user = get_user_model().objects.create_user(username=f"{request_id}@example.com")
    request = Request.objects.create(request_id=request_id, request_type="raes-range", user=user)
    range_row = Range.objects.create(
        workspace_id=_WORKSPACE_ID,
        request=request,
        user=user,
        status=range_status,
        provisioner_operation_id=uuid4(),
    )
    if with_claimed_generation:
        WarmRangeGeneration.objects.create(
            bucket_id="gce-polaris",
            compatibility_digest="sha256:" + "a" * 64,
            effective_policy_fingerprint="sha256:" + "f" * 64,
            backend="gce",
            range_source="mission-control",
            capacity_partition="default",
            capacity_scope_ref=uuid4(),
            capacity_draw_key=uuid4(),
            request_id=request_id,
            state=WarmRangeGeneration.State.CLAIMED,
            claimed_by_request_id=uuid4(),
            claimed_at=timezone.now(),
        )
    return request, range_row


class TestAuthorizeWarmActivation:
    def test_claimed_generation_on_quarantined_range_is_authorized(self):
        request, range_row = _seed()
        # No exception: a claimed generation on a PROVISIONING range authorizes activation.
        authorize_warm_activation(request, range_row)

    def test_no_claimed_generation_rejected(self):
        request, range_row = _seed(with_claimed_generation=False)
        with pytest.raises(ValueError, match="no claimed warm generation"):
            authorize_warm_activation(request, range_row)

    def test_non_provisioning_range_rejected(self):
        request, range_row = _seed(range_status=Range.Status.READY)
        with pytest.raises(ValueError, match="range state does not authorize activation"):
            authorize_warm_activation(request, range_row)


class TestActivateAuthorizationDelegation:
    def test_activate_payload_authorized_through_launch_intents(self):
        request, range_row = _seed()
        payload = {
            "version": 1,
            "resource": "raes-range",
            "operation": "activate",
            "request_id": str(request.request_id),
        }
        # Delegates to warm_activation_authz; a claimed generation authorizes it.
        authorize_provisioner_payload(payload, target=range_row)

    def test_activate_payload_rejected_without_claim(self):
        request, range_row = _seed(with_claimed_generation=False)
        payload = {
            "version": 1,
            "resource": "raes-range",
            "operation": "activate",
            "request_id": str(request.request_id),
        }
        with pytest.raises(ValueError):
            authorize_provisioner_payload(payload, target=range_row)
