"""Application-policy lifecycle authority for human and service principals."""

from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIRequestFactory, force_authenticate

from management import admin_services, lifecycle, password_reset
from management.models import Principal
from management.services import AuditContext
from shared.authorization import AuthorizationDecision, CredentialCeiling, DecisionKind
from shared.credentials import CredentialContext
from shared.identity_scope import PrincipalRef
from shared.models import AuditLog

pytestmark = pytest.mark.django_db


class Provider:
    def __init__(self, allowed=True):
        self.allowed = allowed
        self.requests = []

    def check(self, request):
        self.requests.append(request)
        return AuthorizationDecision(
            DecisionKind.ALLOWED if self.allowed else DecisionKind.DENIED,
            "policy_allowed" if self.allowed else "policy_denied",
        )


def _service_actor():
    principal = Principal.objects.create(kind="service", name="Administrator")
    return CredentialContext(
        PrincipalRef(principal.uuid, "service"),
        "service",
        uuid4(),
        CredentialCeiling(frozenset({"installation.manage_principals"})),
        frozenset(),
    )


def test_service_administrator_can_deactivate_human_with_strict_principal_audit():
    target = get_user_model().objects.create_user(username="target")
    actor = _service_actor()
    provider = Provider()

    state = lifecycle.transition_account(
        target,
        action=lifecycle.AccountLifecycleAction.DEACTIVATE,
        actor=actor,
        provider=provider,
        audit=AuditContext(actor_type="system", actor_id=None, request_id="test-request"),
    )

    target.refresh_from_db()
    assert state == lifecycle.AccountLifecycleState.DEACTIVATED
    assert not target.is_active
    assert provider.requests[0].action == "installation.manage_principals"
    event = AuditLog.objects.filter(
        entity_type="user", entity_id=target.id, context="account lifecycle deactivate"
    ).get()
    assert event.actor_principal_uuid == actor.principal.uuid
    assert event.request_id == "test-request"


def test_policy_denial_and_missing_provider_leave_user_active():
    target = get_user_model().objects.create_user(username="target")
    actor = _service_actor()
    for provider in (Provider(allowed=False), None):
        with pytest.raises(lifecycle.AccountLifecycleError):
            lifecycle.transition_account(
                target,
                action=lifecycle.AccountLifecycleAction.DEACTIVATE,
                actor=actor,
                provider=provider,
                audit=AuditContext(actor_type="system", actor_id=None),
            )
        target.refresh_from_db()
        assert target.is_active


def test_policy_human_cannot_disable_self_even_with_full_authority():
    user = get_user_model().objects.create_user(username="self")
    principal = Principal.objects.get(user=user)
    actor = CredentialContext(
        PrincipalRef(principal.uuid, "human"),
        "session",
        uuid4(),
        CredentialCeiling(frozenset({"installation.manage_principals"})),
        frozenset(),
    )

    with pytest.raises(lifecycle.AccountLifecycleError) as error:
        lifecycle.transition_account(
            user,
            action=lifecycle.AccountLifecycleAction.DEACTIVATE,
            actor=actor,
            provider=Provider(),
            audit=AuditContext(actor_type="user", actor_id=user.id),
        )
    assert error.value.code == "self_action_forbidden"
    user.refresh_from_db()
    assert user.is_active


def test_service_admin_can_manage_superuser_but_cannot_disable_last_one():
    user_model = get_user_model()
    first = user_model.objects.create_superuser(username="first", email="first@example.com", password="pw")
    second = user_model.objects.create_superuser(username="second", email="second@example.com", password="pw")
    actor = _service_actor()

    lifecycle.transition_account(
        first,
        action=lifecycle.AccountLifecycleAction.DEACTIVATE,
        actor=actor,
        provider=Provider(),
        audit=AuditContext(actor_type="principal", actor_id=None),
    )
    with pytest.raises(lifecycle.AccountLifecycleError) as error:
        lifecycle.transition_account(
            second,
            action=lifecycle.AccountLifecycleAction.DEACTIVATE,
            actor=actor,
            provider=Provider(),
            audit=AuditContext(actor_type="principal", actor_id=None),
        )
    assert error.value.code == "last_superuser_protected"
    second.refresh_from_db()
    assert second.is_active


def test_policy_user_list_checks_installation_authority_before_count():
    target = get_user_model().objects.create_user(username="target")
    actor = _service_actor()
    provider = Provider()

    rows = admin_services.list_policy_admin_users(actor, provider, search="target")

    assert list(rows.values_list("id", flat=True)) == [target.id]
    assert provider.requests[0].action == "installation.manage_principals"
    with pytest.raises(PermissionError):
        admin_services.list_policy_admin_users(actor, Provider(allowed=False), search="target").count()


def test_policy_administer_api_admits_service_and_enforces_live_policy(monkeypatch):
    from management.api.policy_views import (
        PolicyAdminUserDetailView,
        PolicyAdminUserLifecycleView,
        PolicyAdminUserListView,
    )

    target = get_user_model().objects.create_user(username="target")
    actor = _service_actor()
    provider = Provider()
    monkeypatch.setattr("management.api.policy_views.configured_authorization_provider", lambda: provider)

    listing = APIRequestFactory().get("/api/v1/administer/users/")
    listing.credential_context = actor
    force_authenticate(listing, token=actor)
    list_response = PolicyAdminUserListView.as_view()(listing)

    assert list_response.status_code == 200
    assert any(row["id"] == target.id for row in list_response.data["results"])

    detail = APIRequestFactory().get(f"/api/v1/administer/users/{target.id}/")
    detail.credential_context = actor
    force_authenticate(detail, token=actor)
    detail_response = PolicyAdminUserDetailView.as_view()(detail, pk=target.id)
    assert detail_response.status_code == 200
    assert detail_response.data["id"] == target.id

    command = APIRequestFactory().post(
        f"/api/v1/administer/users/{target.id}/lifecycle/", {"action": "deactivate"}, format="json"
    )
    command.credential_context = actor
    force_authenticate(command, token=actor)
    transition_response = PolicyAdminUserLifecycleView.as_view()(command, pk=target.id)
    assert transition_response.status_code == 200
    target.refresh_from_db()
    assert not target.is_active

    monkeypatch.setattr(
        "management.api.policy_views.configured_authorization_provider", lambda: Provider(allowed=False)
    )
    denied = APIRequestFactory().get("/api/v1/administer/users/")
    denied.credential_context = actor
    force_authenticate(denied, token=actor)
    assert PolicyAdminUserListView.as_view()(denied).status_code == 403


def test_service_admin_lifecycle_response_includes_available_superuser_action(monkeypatch):
    from management.api.policy_views import PolicyAdminUserLifecycleView

    user_model = get_user_model()
    target = user_model.objects.create_superuser(username="first", email="first@example.com", password="pw")
    user_model.objects.create_superuser(username="second", email="second@example.com", password="pw")
    actor = _service_actor()
    monkeypatch.setattr("management.api.policy_views.configured_authorization_provider", Provider)
    request = APIRequestFactory().post(
        f"/api/v1/administer/users/{target.id}/lifecycle/", {"action": "deactivate"}, format="json"
    )
    request.credential_context = actor
    force_authenticate(request, token=actor)

    response = PolicyAdminUserLifecycleView.as_view()(request, pk=target.id)

    assert response.status_code == 200
    assert "activate" in response.data["available_actions"]


def test_service_admin_password_reset_checks_policy_before_delivery(settings, django_capture_on_commit_callbacks):
    settings.SITE_URL = "https://portal.example.com"
    settings.DEBUG = False
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    target = get_user_model().objects.create_user(username="reset-target", email="reset@example.com", password="pw")
    actor = _service_actor()
    audit = AuditContext(actor_type="principal", actor_id=None, request_id="reset-request")

    with pytest.raises(PermissionError):
        password_reset.request_password_reset(target, audit=audit, actor=actor, provider=Provider(allowed=False))
    assert not AuditLog.objects.filter(context="administrator password reset requested", entity_id=target.id).exists()

    with django_capture_on_commit_callbacks(execute=True):
        password_reset.request_password_reset(target, audit=audit, actor=actor, provider=Provider())
    event = AuditLog.objects.get(context="administrator password reset requested", entity_id=target.id)
    assert event.actor_principal_uuid == actor.principal.uuid
    assert event.request_id == "reset-request"


def test_service_admin_password_reset_http_adapter(settings, monkeypatch):
    from management.api.policy_views import PolicyAdminUserResetPasswordView

    settings.SITE_URL = "https://portal.example.com"
    settings.DEBUG = False
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    target = get_user_model().objects.create_user(username="reset-api", email="reset-api@example.com", password="pw")
    actor = _service_actor()
    monkeypatch.setattr("management.api.policy_views.configured_authorization_provider", Provider)
    request = APIRequestFactory().post(f"/api/v1/administer/users/{target.pk}/reset-password/", {}, format="json")
    request.credential_context = actor
    force_authenticate(request, token=actor)

    response = PolicyAdminUserResetPasswordView.as_view()(request, pk=target.pk)

    assert response.status_code == 200
    assert AuditLog.objects.filter(
        context="administrator password reset requested", entity_id=target.id, actor_principal_uuid=actor.principal.uuid
    ).exists()


def test_service_admin_compatibility_lifecycle_commands(monkeypatch):
    from management.api.policy_views import PolicyAdminUserDeleteView, PolicyAdminUserSetActiveView

    first = get_user_model().objects.create_user(username="compat-active")
    second = get_user_model().objects.create_user(username="compat-delete")
    actor = _service_actor()
    monkeypatch.setattr("management.api.policy_views.configured_authorization_provider", Provider)

    active_request = APIRequestFactory().post(
        f"/api/v1/administer/users/{first.pk}/set-active/", {"is_active": False}, format="json"
    )
    active_request.credential_context = actor
    force_authenticate(active_request, token=actor)
    active_response = PolicyAdminUserSetActiveView.as_view()(active_request, pk=first.pk)
    first.refresh_from_db()
    assert active_response.status_code == 200
    assert not first.is_active

    delete_request = APIRequestFactory().post(f"/api/v1/administer/users/{second.pk}/delete/", {}, format="json")
    delete_request.credential_context = actor
    force_authenticate(delete_request, token=actor)
    delete_response = PolicyAdminUserDeleteView.as_view()(delete_request, pk=second.pk)
    second.refresh_from_db()
    assert delete_response.status_code == 200
    assert not second.is_active


@pytest.mark.parametrize(
    ("view_name", "body"),
    [
        ("PolicyAdminUserLifecycleView", {"action": "deactivate"}),
        ("PolicyAdminUserResetPasswordView", {}),
    ],
)
def test_denied_user_commands_do_not_reveal_existing_ids(monkeypatch, view_name, body):
    from management.api import policy_views

    target = get_user_model().objects.create_user(username=f"target-{uuid4()}")
    actor = _service_actor()
    provider = Provider(allowed=False)
    monkeypatch.setattr(policy_views, "configured_authorization_provider", lambda: provider)
    view = getattr(policy_views, view_name).as_view()

    for user_id in (target.pk, target.pk + 100000):
        request = APIRequestFactory().post(f"/api/v1/administer/users/{user_id}/", body, format="json")
        request.credential_context = actor
        force_authenticate(request, token=actor)
        response = view(request, pk=user_id)
        assert response.status_code == 403
        assert response.data["error"]["code"] == "administration_denied"

    assert [request.action for request in provider.requests] == [
        "installation.manage_principals",
        "installation.manage_principals",
    ]
