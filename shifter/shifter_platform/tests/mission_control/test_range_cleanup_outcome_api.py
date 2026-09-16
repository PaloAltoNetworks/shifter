"""API for the truthful range cleanup-outcome projection (#2086, ADR-063-R4).

Authorized by range ownership: an owner sees the distinct cleanup facts; a
not-owned or unknown request_id is an opaque 404.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


def _outcome(client, request_id):
    return client.get(reverse("v1:mission_control:range-cleanup-outcome", args=[str(request_id)]))


def test_owner_sees_cleanup_outcome_for_active_range(authenticated_client, launch_range_via_api):
    client, user = authenticated_client(email="cleanup-owner@example.com")
    response, _agent, _scenario = launch_range_via_api(client, user)
    request_id = response.json()["range"]["request_id"]

    result = _outcome(client, request_id)

    assert result.status_code == 200, result.content
    body = result.json()
    assert body["found"] is True
    # A freshly launched, active range owes no teardown.
    assert body["cleanup"] == "not_applicable"
    assert body["residual_obligations"] == []


def test_unknown_request_id_is_opaque_404(authenticated_client):
    client, _user = authenticated_client(email="cleanup-unknown@example.com")
    result = _outcome(client, uuid4())
    assert result.status_code == 404, result.content


def test_other_users_range_is_opaque_404(authenticated_client, launch_range_via_api):
    owner_client, owner = authenticated_client(email="cleanup-real-owner@example.com")
    response, _agent, _scenario = launch_range_via_api(owner_client, owner)
    request_id = response.json()["range"]["request_id"]

    other_client, _other = authenticated_client(email="cleanup-intruder@example.com")
    result = _outcome(other_client, request_id)

    assert result.status_code == 404, result.content
