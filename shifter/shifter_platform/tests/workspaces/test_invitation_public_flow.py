"""Public fragment exchange and authenticated invitation handoff tests (#1942)."""

from __future__ import annotations

import json
import re
from urllib.parse import unquote

import pytest
from django.contrib.auth import SESSION_KEY
from django.contrib.auth.models import AnonymousUser
from django.contrib.sessions.middleware import SessionMiddleware
from django.core.cache import cache
from django.test import Client, RequestFactory
from django.urls import reverse

from config.workspace_invitation_auth import (
    attach_fresh_verified_identity,
    consume_staged_workspace_invitation,
)
from shared.verified_identity import VerifiedIdentity
from shared.workspace_invitation_handoff import (
    INVITATION_OUTCOME_SESSION_KEY,
    POST_LOGIN_CONTINUATION_SESSION_KEY,
    STAGED_INVITATION_SESSION_KEY,
)
from workspaces import services
from workspaces.models import Organization, Workspace, WorkspaceMembership
from workspaces.roles import WorkspaceRole

pytestmark = pytest.mark.django_db(transaction=True)
_TOKEN_RE = re.compile(r"#token=([^\s<\"']+)")


def _setup(django_user_model, settings, recorded_workspace_email):
    settings.SITE_URL = "https://shifter.example.test"
    owner = django_user_model.objects.create_user(
        username="public-flow-owner@example.com",
        email="public-flow-owner@example.com",
        is_staff=True,
    )
    invitee = django_user_model.objects.create_user(
        username="public-flow-invitee@example.com",
        email="public-flow-invitee@example.com",
    )
    workspace = Workspace.objects.create(
        organization=Organization.objects.create(name="Public Flow Lab"),
        name="Public Flow Workspace",
    )
    WorkspaceMembership.objects.create(workspace=workspace, user=owner, role=WorkspaceRole.OWNER)
    services.issue_workspace_invitation(
        owner,
        workspace.uuid,
        invitee.email,
        WorkspaceRole.MEMBER,
        audit=services.MembershipAuditContext(actor_type="user", actor_id=owner.pk),
    )
    message = recorded_workspace_email.get(timeout=2)
    match = _TOKEN_RE.search(message.body)
    assert match
    return owner, invitee, workspace, unquote(match.group(1))


def _request_with_session():
    request = RequestFactory().get(reverse("workspace_invitation_accept"))
    SessionMiddleware(lambda value: value).process_request(request)
    request.session.save()
    request.user = AnonymousUser()
    return request


def test_landing_serves_external_exchange_script_with_private_headers():
    response = Client().get(reverse("workspace_invitation_accept"))

    assert response.status_code == 200
    assert "no-store" in response.headers["Cache-Control"]
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert b"workspace_invitation_accept.js" in response.content


def test_stage_requires_csrf_and_stores_no_raw_token(django_user_model, settings, recorded_workspace_email):
    cache.clear()
    _owner, _invitee, _workspace, token = _setup(django_user_model, settings, recorded_workspace_email)
    client = Client(enforce_csrf_checks=True)

    denied = client.post(
        reverse("workspace_invitation_stage"),
        json.dumps({"token": token}),
        content_type="application/json",
    )
    client.get(reverse("workspace_invitation_accept"))
    csrf = client.cookies["csrftoken"].value
    accepted = client.post(
        reverse("workspace_invitation_stage"),
        json.dumps({"token": token}),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=csrf,
    )

    assert denied.status_code == 403
    assert accepted.status_code == 200
    assert accepted.json() == {"redirect_url": reverse("platform_login")}
    staged = client.session[STAGED_INVITATION_SESSION_KEY]
    assert set(staged) == {"invitation_uuid", "generation"}
    assert token not in json.dumps(dict(client.session))
    assert "no-store" in accepted.headers["Cache-Control"]
    assert accepted.headers["Referrer-Policy"] == "no-referrer"


def test_authenticated_landing_forces_fresh_login_while_preserving_staged_claim(
    django_user_model, settings, recorded_workspace_email
):
    settings.AUTH_PROVIDER = "oidc"
    _owner, invitee, _workspace, token = _setup(django_user_model, settings, recorded_workspace_email)
    client = Client()
    client.force_login(invitee)
    client.get(reverse("workspace_invitation_accept"))
    staged_response = client.post(
        reverse("workspace_invitation_stage"),
        json.dumps({"token": token}),
        content_type="application/json",
    )
    staged = client.session[STAGED_INVITATION_SESSION_KEY]

    response = client.get(reverse("platform_login"))

    assert staged_response.status_code == 200
    assert response.status_code == 302
    assert response.url == reverse("oidc_authentication_init")
    assert SESSION_KEY not in client.session
    assert client.session[STAGED_INVITATION_SESSION_KEY] == staged


def test_dashboard_consumes_login_signal_continuation_once(django_user_model, settings, recorded_workspace_email):
    _owner, invitee, _workspace, token = _setup(django_user_model, settings, recorded_workspace_email)
    claim = services.stage_workspace_invitation_token(token)
    client = Client()
    session = client.session
    session[STAGED_INVITATION_SESSION_KEY] = {
        "invitation_uuid": str(claim.invitation_uuid),
        "generation": str(claim.generation),
    }
    session.save()

    client.force_login(invitee)
    assert client.session[POST_LOGIN_CONTINUATION_SESSION_KEY] == reverse("workspace_invitation_accept")

    response = client.get(reverse("dashboard_router"))

    assert response.status_code == 302
    assert response.url == reverse("workspace_invitation_accept")
    assert POST_LOGIN_CONTINUATION_SESSION_KEY not in client.session


def test_login_handoff_requires_fresh_identity_then_accepts_once(django_user_model, settings, recorded_workspace_email):
    _owner, invitee, workspace, token = _setup(django_user_model, settings, recorded_workspace_email)
    claim = services.stage_workspace_invitation_token(token)
    request = _request_with_session()
    request.user = invitee
    request.session[STAGED_INVITATION_SESSION_KEY] = {
        "invitation_uuid": str(claim.invitation_uuid),
        "generation": str(claim.generation),
    }
    identity = VerifiedIdentity(
        issuer="https://issuer.example.test",
        subject="public-flow-subject",
        email=invitee.email,
        email_verified=True,
        source="test",
    )
    attach_fresh_verified_identity(request, identity)

    consume_staged_workspace_invitation(object(), request, invitee)

    assert WorkspaceMembership.objects.filter(workspace=workspace, user=invitee).count() == 1
    assert request.session[INVITATION_OUTCOME_SESSION_KEY]["status"] == "accepted"
    assert request.session[POST_LOGIN_CONTINUATION_SESSION_KEY] == reverse("workspace_invitation_accept")
    assert STAGED_INVITATION_SESSION_KEY not in request.session


def test_login_handoff_without_fresh_provider_evidence_fails_closed(
    django_user_model, settings, recorded_workspace_email
):
    _owner, invitee, workspace, token = _setup(django_user_model, settings, recorded_workspace_email)
    claim = services.stage_workspace_invitation_token(token)
    request = _request_with_session()
    request.user = invitee
    request.session[STAGED_INVITATION_SESSION_KEY] = {
        "invitation_uuid": str(claim.invitation_uuid),
        "generation": str(claim.generation),
    }

    consume_staged_workspace_invitation(object(), request, invitee)

    assert not WorkspaceMembership.objects.filter(workspace=workspace, user=invitee).exists()
    assert request.session[INVITATION_OUTCOME_SESSION_KEY] == {
        "status": "failed",
        "code": "invitation_invalid",
    }
