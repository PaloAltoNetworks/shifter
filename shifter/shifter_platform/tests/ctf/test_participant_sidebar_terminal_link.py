"""CTF participant sidebar must expose the Mission Control Terminal nav link (#200).

The walkthrough page tells participants to open Terminal from the sidebar, but
``ctf_participant_sidebar.html`` previously omitted that entry while Mission
Control's ``icon_sidebar.html`` already links ``mission_control:terminal``.
"""

from __future__ import annotations

import pytest
from django.template.loader import render_to_string
from django.urls import reverse


@pytest.mark.django_db
def test_ctf_participant_sidebar_renders_terminal_nav_link(participant_user):
    html = render_to_string(
        "partials/ctf_participant_sidebar.html",
        {"user": participant_user, "active_nav": ""},
    )
    terminal_url = reverse("mission_control:terminal")
    assert f'href="{terminal_url}"' in html
    assert "Terminal" in html


@pytest.mark.django_db
def test_ctf_participant_dashboard_includes_terminal_sidebar_link(authenticated_participant_client, ctf_participant):
    response = authenticated_participant_client.get(reverse("ctf:participant_dashboard"))
    assert response.status_code == 200
    terminal_url = reverse("mission_control:terminal")
    assert terminal_url.encode() in response.content
    assert b"Terminal" in response.content


@pytest.mark.django_db
def test_ctf_participant_can_open_terminal_page(authenticated_participant_client, ctf_participant):
    response = authenticated_participant_client.get(reverse("mission_control:terminal"))
    assert response.status_code == 200
