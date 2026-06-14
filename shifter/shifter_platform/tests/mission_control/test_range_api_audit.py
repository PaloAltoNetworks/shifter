"""Behavior tests for HTTP-layer audit logging of range lifecycle actions (#694).

Each range lifecycle endpoint must record a real ``AuditLog`` row carrying the
acting user and request context. These tests drive the endpoints and assert the
persisted audit rows instead of patching ``audit_log_from_request`` and
inspecting call kwargs.
"""

import json

import pytest
from django.test import Client
from django.urls import reverse

from risk_register.models import AuditLog

pytestmark = pytest.mark.django_db

GHOST_REQUEST_ID = "00000000-0000-0000-0000-000000000000"


def _range_audit(action):
    return AuditLog.objects.filter(entity_type=AuditLog.EntityType.RANGE, action=action)


def _has_http_audit(action, *, actor_id, request_id, scenario=None):
    """True if an HTTP-layer audit row for this action carries the request context.

    Both the view (HTTP boundary) and the CMS service layer audit a lifecycle
    action, so we assert the HTTP-layer row is present rather than that it is
    the only row.
    """
    for row in _range_audit(action):
        state = row.new_state or {}
        if row.actor_id != actor_id or state.get("request_id") != request_id:
            continue
        if scenario is not None and state.get("scenario") != scenario:
            continue
        return True
    return False


class TestRangeLifecycleAudit:
    def test_launch_records_provision_audit(self, authenticated_client, launch_range_via_api):
        client, user = authenticated_client(email="audit-launch@example.com")
        response, _agent, scenario_id = launch_range_via_api(client, user)
        assert response.status_code == 200
        request_id = json.loads(response.content)["range"]["request_id"]

        # The HTTP boundary recorded a PROVISION audit row carrying the actor
        # and request context.
        assert _has_http_audit(AuditLog.Action.PROVISION, actor_id=user.id, request_id=request_id, scenario=scenario_id)

    def test_cancel_records_cancel_audit(self, authenticated_client, launch_range_via_api):
        client, user = authenticated_client(email="audit-cancel@example.com")
        launch_resp, _agent, _scenario = launch_range_via_api(client, user)
        request_id = json.loads(launch_resp.content)["range"]["request_id"]

        response = client.post(
            reverse("mission_control:cancel_range"),
            data=json.dumps({"request_id": request_id}),
            content_type="application/json",
        )
        assert response.status_code == 200

        assert _has_http_audit(AuditLog.Action.CANCEL, actor_id=user.id, request_id=request_id)

    def test_failed_action_does_not_audit(self, authenticated_client):
        client, _user = authenticated_client(email="audit-fail@example.com")
        response = client.post(
            reverse("mission_control:destroy_range"),
            data=json.dumps({"request_id": GHOST_REQUEST_ID}),
            content_type="application/json",
        )
        assert response.status_code == 400
        # A rejected action records no DEPROVISION audit row.
        assert not _range_audit(AuditLog.Action.DEPROVISION).exists()

    def test_requires_login_records_no_audit(self):
        response = Client().post(
            reverse("mission_control:launch_range"),
            data="{}",
            content_type="application/json",
        )
        assert response.status_code == 302
        assert not _range_audit(AuditLog.Action.PROVISION).exists()
