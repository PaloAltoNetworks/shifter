"""Regression coverage for removal of the retired feature surface."""

from __future__ import annotations

import hashlib
import importlib.util

import pytest
from django.apps import apps
from rest_framework.test import APIClient

from shared.api_tokens.models import ApiToken
from shared.api_tokens.scopes import KNOWN_SCOPES

pytestmark = pytest.mark.django_db

REMOVED_APP = "risk_register"
REMOVED_SCOPE_PREFIX = "risk:"


def test_removed_app_is_not_installed_or_importable():
    assert not apps.is_installed(REMOVED_APP)
    assert importlib.util.find_spec(REMOVED_APP) is None


def test_removed_api_routes_return_not_found():
    client = APIClient()

    assert client.get("/api/v1/risks/").status_code == 404
    assert client.get("/api/v1/risks/1/comments/").status_code == 404


def test_removed_token_scopes_are_not_registered():
    assert not any(scope.startswith(REMOVED_SCOPE_PREFIX) for scope in KNOWN_SCOPES)


def test_token_with_only_removed_scope_fails_closed_without_raising(django_user_model):
    user = django_user_model.objects.create_user(username="retired-token-owner")
    secret = "stale-scope-secret"
    token = ApiToken.objects.create(
        name="retired-scope",
        token_id="retired-scope-id",
        verifier_hash=hashlib.sha256(secret.encode()).hexdigest(),
        scopes=[f"{REMOVED_SCOPE_PREFIX}read"],
        created_by=user,
    )

    assert token.has_usable_scope is False
    assert ApiToken.authenticate(f"shf_{token.token_id}.{secret}") is None
