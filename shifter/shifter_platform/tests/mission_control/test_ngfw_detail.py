"""Behavior tests for the ngfw_detail view in mission_control/views.

Drives the real view → real ``cms.services.get_ngfw`` (against a real CMS NGFW
``App``) → real ``engine.services.get_ranges_for_ngfw`` (against real engine
NGFW ``Instance`` + linked ``Range`` rows, correlated by the shared
``request_id``) → the real ``ngfw/detail.html`` template, instead of patching
``cms_get_ngfw`` / ``get_ranges_for_ngfw`` / ``render``. Assertions read the
rendered response.
"""

import time
from pathlib import Path
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

pytestmark = pytest.mark.django_db

User = get_user_model()


@pytest.fixture
def user(db):
    return User.objects.create_user(username="ngfw-detail@example.com", email="ngfw-detail@example.com")


@pytest.fixture
def other_user(db):
    return User.objects.create_user(username="ngfw-detail-other@example.com", email="ngfw-detail-other@example.com")


@pytest.fixture
def client_for(db):
    def _make(user):
        client = Client()
        client.force_login(user)
        session = client.session
        session["oidc_id_token_expiration"] = time.time() + 3600
        session.save()
        return client

    return _make


def _engine_ngfw_with_range(user, request_id, *, range_status="ready"):
    """Create the engine side of an NGFW (Request + role=ngfw Instance) keyed by
    the shared ``request_id``, plus a Range attached to it.

    Returns the created Range.
    """
    from engine.models import Instance, Range, Request
    from shared.enums import RequestType

    engine_request = Request.objects.create(request_id=request_id, request_type=RequestType.NGFW.value, user=user)
    ngfw_instance = Instance.objects.create(request=engine_request, role=Instance.Role.NGFW)
    return Range.objects.create(user=user, status=range_status, ngfw_instance=ngfw_instance)


class TestNGFWDetailView:
    def test_renders_linked_ranges_when_present(self, user, client_for, cms_ngfw_app):
        app = cms_ngfw_app(user, name="DevNGFW")
        # Engine NGFW Instance + attached range, correlated by the shared request_id.
        rng = _engine_ngfw_with_range(user, app.instance.request.request_id)

        response = client_for(user).get(reverse("mission_control:ngfw_detail", kwargs={"app_id": str(app.id)}))

        assert response.status_code == 200
        body = response.content.decode()
        assert "DevNGFW" in body
        assert "No ranges are currently using this NGFW" not in body
        assert str(rng.pk) in body

    def test_renders_empty_state_when_no_linked_ranges(self, user, client_for, cms_ngfw_app):
        app = cms_ngfw_app(user, name="LonelyNGFW")

        response = client_for(user).get(reverse("mission_control:ngfw_detail", kwargs={"app_id": str(app.id)}))

        assert response.status_code == 200
        body = response.content.decode()
        assert "LonelyNGFW" in body
        assert "No ranges are currently using this NGFW" in body

    def test_excludes_ranges_attached_to_other_ngfws(self, user, client_for, cms_ngfw_app):
        """A range attached to a different NGFW's instance is not shown."""
        app = cms_ngfw_app(user, name="MineNGFW")
        # A range attached to an unrelated engine NGFW (different request_id).
        _engine_ngfw_with_range(user, uuid4())

        response = client_for(user).get(reverse("mission_control:ngfw_detail", kwargs={"app_id": str(app.id)}))

        assert response.status_code == 200
        assert "No ranges are currently using this NGFW" in response.content.decode()

    def test_redirects_to_list_when_ngfw_missing(self, user, client_for):
        response = client_for(user).get(reverse("mission_control:ngfw_detail", kwargs={"app_id": str(uuid4())}))

        assert response.status_code == 302
        assert reverse("mission_control:ngfw_list") in response.url

    def test_redirects_when_ngfw_owned_by_other_user(self, user, other_user, client_for, cms_ngfw_app):
        app = cms_ngfw_app(other_user, name="NotYours")

        response = client_for(user).get(reverse("mission_control:ngfw_detail", kwargs={"app_id": str(app.id)}))

        assert response.status_code == 302
        assert reverse("mission_control:ngfw_list") in response.url


NGFW_DETAIL_TEMPLATE = Path(__file__).resolve().parents[2] / "templates" / "mission_control" / "ngfw" / "detail.html"


def test_ngfw_detail_template_has_no_inline_style_attributes():
    content = NGFW_DETAIL_TEMPLATE.read_text(encoding="utf-8")
    assert 'style="' not in content, "ngfw/detail.html still contains inline style= attributes"
