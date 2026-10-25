"""The shared OpenVPN pool controller's private API (#2480).

Only the configured pool service account may call it. Google's token
verification is the external boundary and is the only thing replaced here;
ranges and sessions are real rows.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APIClient

from engine.models import Range, Request, VpnSession, VpnSessionState
from shared.remote_access import bind_openvpn_realization, build_openvpn_capability

pytestmark = pytest.mark.django_db

_AUDIENCE = "https://portal.example.com/vpn-control"
_EMAIL = "vpn-pool@example-project.iam.gserviceaccount.com"
_SUBJECT = "123456789012345678901"
_TARGET = "provision.node.kali#0"
_SIGNED_ASSERTION = "signed-token"
_POOL_IDENTITY = {
    "VPN_CONTROL_AUDIENCE": _AUDIENCE,
    "VPN_CONTROLLER_SERVICE_ACCOUNT_EMAIL": _EMAIL,
    "VPN_CONTROLLER_SERVICE_ACCOUNT_ID": _SUBJECT,
}


@pytest.fixture
def pool_identity(settings):
    """Configure the pool service account the API admits."""
    for name, value in _POOL_IDENTITY.items():
        setattr(settings, name, value)


@pytest.fixture
def google_claims(monkeypatch, pool_identity):
    """Replace only Google's signature check; the claims it returns are under test control."""
    claims = {"email": _EMAIL, "email_verified": True, "sub": _SUBJECT}
    seen = []

    def verify(token, request, audience=None):
        seen.append((token, audience))
        if token != "signed-token":
            raise ValueError("bad signature")
        return dict(claims)

    monkeypatch.setattr("google.oauth2.id_token.verify_oauth2_token", verify)
    return claims, seen


def _ready_range() -> Range:
    user = get_user_model().objects.create_user(username=f"{uuid4()}@example.com")
    request = Request.objects.create(request_id=uuid4(), request_type="range", user=user)
    realization = {
        "generation": str(request.request_id),
        "target_ref": _TARGET,
        "endpoint": "203.0.113.7",
        "port": 1194,
        "secret_ref": "projects/p/secrets/profile",
    }
    return Range.objects.create(
        workspace_id=1,
        request=request,
        user=user,
        status=Range.Status.READY,
        range_backend="gce",
        remote_access_capability=build_openvpn_capability(_TARGET, datetime.now(UTC) + timedelta(days=2)),
        vpn_access_binding=bind_openvpn_realization(realization, user.id),
        provisioned_instances=[
            {"uuid": _TARGET, "role": "raes-node", "private_ip": "10.50.3.3", "participant_access_channels": ["ssh"]}
        ],
    )


def _post(name: str, body: dict, *, credential: str | None = _SIGNED_ASSERTION):
    client = APIClient()
    if credential is not None:
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {credential}")
    return client.post(reverse(f"v1:cms:{name}"), body, format="json")


class TestControllerIdentity:
    @pytest.mark.parametrize(
        "claim",
        [
            {"email": "other@example-project.iam.gserviceaccount.com"},
            {"sub": "100000000000000000001"},
            {"email_verified": False},
        ],
        ids=["other-email", "other-subject", "unverified"],
    )
    def test_any_other_identity_is_refused(self, google_claims, claim):
        claims, _seen = google_claims
        claims.update(claim)

        response = _post("vpn-control-heartbeat", {"server": "vpn-a", "sessions": []})

        assert response.status_code in (401, 403)

    def test_a_bad_signature_or_missing_token_is_refused(self, google_claims):
        assert _post("vpn-control-heartbeat", {"server": "vpn-a", "sessions": []}, credential="forged").status_code in (
            401,
            403,
        )
        assert _post("vpn-control-heartbeat", {"server": "vpn-a", "sessions": []}, credential=None).status_code in (
            401,
            403,
        )

    def test_a_logged_in_administrator_is_not_the_controller(self, google_claims):
        admin = get_user_model().objects.create_superuser(username="admin@example.com", password="x" * 16)
        client = APIClient()
        client.force_login(admin)

        response = client.post(
            reverse("v1:cms:vpn-control-heartbeat"), {"server": "vpn-a", "sessions": []}, format="json"
        )

        assert response.status_code in (401, 403)

    def test_the_token_is_checked_against_the_configured_audience(self, google_claims):
        _claims, seen = google_claims
        _post("vpn-control-heartbeat", {"server": "vpn-a", "sessions": []})
        assert seen == [("signed-token", _AUDIENCE)]


def test_an_unconfigured_installation_refuses_every_controller_request(google_claims, settings):
    for name in _POOL_IDENTITY:
        setattr(settings, name, "")
    response = _post("vpn-control-heartbeat", {"server": "vpn-a", "sessions": []})
    assert response.status_code in (401, 403)


class TestSessionLifecycle:
    def test_authorize_heartbeat_and_disconnect(self, google_claims):
        range_obj = _ready_range()

        granted = _post(
            "vpn-control-authorize",
            {
                "common_name": f"participant-{range_obj.request.request_id}",
                "server": "vpn-a",
                "client_id": 4,
                "client_address": "198.51.100.20",
            },
        )
        assert granted.status_code == 201
        body = granted.json()
        assert (body["target"], body["ports"]) == ("10.50.3.3", [22])
        assert body["heartbeat_seconds"] < body["lease_seconds"]

        beat = _post("vpn-control-heartbeat", {"server": "vpn-a", "sessions": [body["session"]]})
        assert beat.status_code == 200
        assert beat.json()["disconnect"] == []

        ended = _post("vpn-control-end", {"server": "vpn-a", "session": body["session"]})
        assert ended.status_code == 204
        assert VpnSession.objects.get(pk=body["session"]).state == VpnSessionState.ENDED

    def test_refusals_disclose_only_a_closed_code(self, google_claims):
        unknown = _post(
            "vpn-control-authorize", {"common_name": f"participant-{uuid4()}", "server": "vpn-a", "client_id": 1}
        )
        assert (unknown.status_code, unknown.json()) == (403, {"error": "vpn.unknown_client"})

        malformed = _post("vpn-control-heartbeat", {"server": "vpn-a", "sessions": "x"})
        assert (malformed.status_code, malformed.json()) == (400, {"error": "vpn.invalid_request"})
