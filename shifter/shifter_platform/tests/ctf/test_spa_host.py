"""CTF workspace hard-cut routing behavior (#1311)."""

import pytest
from django.test import Client
from django.urls import resolve

from ctf import views
from shared.spa_host import platform_spa_host

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    "url",
    [
        "/ctf/",
        "/ctf/challenges/",
        "/ctf/team/join/",
        "/ctf/admin/",
        "/ctf/admin/events/create/",
        "/ctf/admin/events/00000000-0000-4000-8000-000000000001/participants/import/",
    ],
)
def test_workspace_pages_are_always_spa_owned(authenticated_organizer_client, url):
    response = authenticated_organizer_client.get(url)
    assert response.status_code == 200
    assert b'id="root"' in response.content


def test_legacy_workspace_posts_are_not_routed(authenticated_organizer_client):
    response = authenticated_organizer_client.post("/ctf/admin/events/create/", {})
    assert response.status_code == 405


def test_login_and_change_password_remain_server_owned():
    assert resolve("/ctf/login/").func is views.ctf_login
    assert resolve("/ctf/change-password/").func is views.ctf_change_password
    assert resolve("/ctf/admin/events/create/").func is platform_spa_host
    assert b'id="root"' not in Client().get("/ctf/login/").content


@pytest.mark.parametrize(
    "unslashed,slashed",
    [
        ("/ctf/login", "/ctf/login/"),
        ("/ctf/change-password", "/ctf/change-password/"),
    ],
)
def test_server_routes_redirect_to_slashed_form_not_spa(unslashed, slashed):
    # The SPA catch-all must not swallow the unslashed server routes; Django's
    # APPEND_SLASH should 301-redirect them to the canonical slashed path
    # instead of silently serving the SPA shell (the trailing-slash footgun).
    response = Client().get(unslashed)
    assert response.status_code == 301
    assert response["Location"].endswith(slashed)
    assert b'id="root"' not in response.content
