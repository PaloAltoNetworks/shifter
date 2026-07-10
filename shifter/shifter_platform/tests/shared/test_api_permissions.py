"""Tests for shared DRF API permissions."""

from __future__ import annotations

import pytest
from django.contrib.auth.models import AnonymousUser
from rest_framework.test import APIRequestFactory

from shared.api.permissions import IsAuthenticatedSessionOrApiToken
from shared.api_tokens import scopes
from shared.api_tokens.models import ApiToken

pytestmark = pytest.mark.django_db


def test_schema_permission_allows_authenticated_session_user(django_user_model) -> None:
    user = django_user_model.objects.create_user(username="session", password="pw")
    request = APIRequestFactory().get("/api/v1/schema/")
    request.user = user
    request.auth = None

    assert IsAuthenticatedSessionOrApiToken().has_permission(request, view=None) is True


def test_schema_permission_allows_valid_platform_api_token(django_user_model) -> None:
    owner = django_user_model.objects.create_user(username="owner", password="pw")
    token, _ = ApiToken.create_token(name="schema", created_by=owner, scopes=[scopes.RISK_READ])
    request = APIRequestFactory().get("/api/v1/schema/")
    request.user = AnonymousUser()
    request.auth = token

    assert IsAuthenticatedSessionOrApiToken().has_permission(request, view=None) is True


def test_schema_permission_rejects_anonymous_request() -> None:
    request = APIRequestFactory().get("/api/v1/schema/")
    request.user = AnonymousUser()
    request.auth = None

    assert IsAuthenticatedSessionOrApiToken().has_permission(request, view=None) is False
