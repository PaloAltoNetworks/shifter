"""The retry-safe public-operation lookup facade (#2086, ADR-063).

``operation_id_for_request`` resolves the current operation generation stamped on
a request's range through the ``engine.services`` facade (ADR-001), returning the
canonical string generation or ``None`` when there is no range or no generation.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model

from engine.models import Range, Request
from engine.services import operation_id_for_request

pytestmark = pytest.mark.django_db

# Opaque #1325 workspace scope binding (ADR-046-R3); a fixed scalar stands in for
# the value the CMS launch facade resolves in production.
_WORKSPACE_ID = 1


def _range(*, operation_id):
    user = get_user_model().objects.create_user(username=f"{uuid4()}@example.com")
    request = Request.objects.create(request_id=uuid4(), request_type="range", user=user)
    Range.objects.create(
        workspace_id=_WORKSPACE_ID,
        request=request,
        user=user,
        status=Range.Status.PROVISIONING,
        provisioner_operation_id=operation_id,
    )
    return request.request_id


def test_returns_the_stamped_operation_generation():
    operation_id = uuid4()
    request_id = _range(operation_id=operation_id)
    assert operation_id_for_request(request_id) == str(operation_id)


def test_returns_none_when_no_generation_is_stamped():
    request_id = _range(operation_id=None)
    assert operation_id_for_request(request_id) is None


def test_returns_none_when_no_range_exists():
    assert operation_id_for_request(uuid4()) is None
