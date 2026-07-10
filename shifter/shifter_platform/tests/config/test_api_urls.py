"""Tests for the canonical platform API URL mount."""

from __future__ import annotations

import pytest
from django.urls import resolve, reverse
from rest_framework.test import APIClient


def test_api_v1_schema_routes_are_namespaced() -> None:
    assert reverse("v1:openapi-schema") == "/api/v1/schema/"
    assert reverse("v1:api-docs") == "/api/v1/docs/"

    schema_match = resolve("/api/v1/schema/")
    docs_match = resolve("/api/v1/docs/")

    assert schema_match.namespace == "v1"
    assert docs_match.namespace == "v1"


def test_existing_risk_register_api_stays_under_v1_namespace() -> None:
    match = resolve("/api/v1/risks/")

    assert match.namespace == "v1"
    assert match.url_name == "risk-list"


@pytest.mark.django_db
def test_openapi_schema_is_authenticated_and_served(django_user_model) -> None:
    client = APIClient()

    assert client.get("/api/v1/schema/").status_code != 200

    user = django_user_model.objects.create_user(username="schema-reader", password="pw")
    client.force_authenticate(user=user)
    response = client.get("/api/v1/schema/")

    assert response.status_code == 200
    schema = response.content.decode()
    assert "openapi:" in schema
    assert "/api/v1/risks/" in schema
    assert "ApiTokenAuth" in schema


@pytest.mark.django_db
def test_swagger_ui_uses_local_sidecar_assets(django_user_model) -> None:
    client = APIClient()

    user = django_user_model.objects.create_user(username="docs-reader", password="pw")
    client.force_authenticate(user=user)
    response = client.get("/api/v1/docs/")

    assert response.status_code == 200
    html = response.content.decode()
    assert "drf_spectacular_sidecar" in html
    assert "cdn.jsdelivr.net" not in html
    assert "unpkg.com" not in html
