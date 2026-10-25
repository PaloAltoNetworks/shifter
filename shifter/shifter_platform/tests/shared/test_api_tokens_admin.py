"""Admin is metadata-only; authorized credential mutations belong to the API."""

import pytest
from django.contrib.admin import site
from django.test import RequestFactory
from knox.models import AuthToken

from shared.api_tokens.admin import ApiTokenAdmin
from shared.api_tokens.models import ApiToken


def test_admin_cannot_mint_edit_delete_or_expose_native_verifiers():
    model_admin = ApiTokenAdmin(ApiToken, site)
    request = RequestFactory().post("/admin/shared/apitoken/add/")
    assert not model_admin.has_add_permission(request)
    assert not model_admin.has_change_permission(request)
    assert not model_admin.has_delete_permission(request)
    assert not site.is_registered(AuthToken)
    for field in ("verifier_hash", "knox_token"):
        assert field not in model_admin.fields
        assert field not in model_admin.list_display
        assert field not in model_admin.search_fields


@pytest.mark.django_db
def test_superuser_cannot_bypass_live_grants_in_admin(client, django_user_model):
    user = django_user_model.objects.create_superuser(username="root", password="test")
    client.force_login(user)
    assert client.post("/admin/shared/apitoken/add/", {"name": "bypass"}).status_code == 403
    assert client.post("/admin/knox/authtoken/add/").status_code == 404
    assert not ApiToken.objects.exists()
