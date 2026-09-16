"""Tests for the neutral session/API-token principal resolver."""

from types import SimpleNamespace

import pytest
from django.contrib.auth.models import AnonymousUser

from shared.api.principals import active_actor_user
from shared.api_tokens.models import ApiToken

pytestmark = pytest.mark.django_db


def _user(django_user_model, suffix: str, *, active: bool = True):
    return django_user_model.objects.create_user(
        username=f"principal-{suffix}@example.com",
        email=f"principal-{suffix}@example.com",
        is_active=active,
    )


def test_session_principal_resolves_active_authenticated_user(django_user_model):
    user = _user(django_user_model, "session")

    assert active_actor_user(SimpleNamespace(user=user, auth=None)) == user


def test_token_principal_resolves_active_created_by_user(django_user_model):
    user = _user(django_user_model, "token")
    token, _ = ApiToken.create_token(name="principal", created_by=user, scopes=["mission_control:range:read"])

    assert active_actor_user(SimpleNamespace(user=AnonymousUser(), auth=token)) == user


@pytest.mark.parametrize("principal_kind", ["session", "token"])
def test_inactive_principal_is_rejected(django_user_model, principal_kind):
    user = _user(django_user_model, principal_kind, active=False)
    token = None
    request_user = user
    if principal_kind == "token":
        token, _ = ApiToken.create_token(
            name="principal",
            created_by=user,
            scopes=["mission_control:range:read"],
        )
        request_user = AnonymousUser()

    assert active_actor_user(SimpleNamespace(user=request_user, auth=token)) is None


def test_anonymous_principal_is_rejected():
    assert active_actor_user(SimpleNamespace(user=AnonymousUser(), auth=None)) is None
