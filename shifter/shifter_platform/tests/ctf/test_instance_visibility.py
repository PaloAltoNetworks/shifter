"""Per-event range-instance visibility policy (#483)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from django.utils import timezone

from ctf.models import CTFParticipant
from ctf.services.range.visibility import ctf_instance_visibility_policy

pytestmark = pytest.mark.django_db


def _instances(*os_types):
    return [SimpleNamespace(os_type=os) for os in os_types]


@pytest.fixture
def ctf_only_user(participant_user):
    """participant_user carries only the CTF Participant group in conftest."""
    return participant_user


def _enroll(event, user):
    return CTFParticipant.objects.create(
        event=event,
        user=user,
        email=user.email,
        name="Viewer",
        status="active",
        registered_at=timezone.now(),
    )


class TestVisibilityPolicy:
    def test_defaults_to_kali_only(self, ctf_event_active, ctf_only_user):
        _enroll(ctf_event_active, ctf_only_user)
        result = ctf_instance_visibility_policy(ctf_only_user, _instances("kali", "ubuntu", "panos"))
        assert [i.os_type for i in result] == ["kali"]

    def test_event_config_widens_visibility(self, ctf_event_active, ctf_only_user):
        ctf_event_active.visible_os_types = ["kali", "ubuntu"]
        ctf_event_active.save(update_fields=["visible_os_types", "updated_at"])
        _enroll(ctf_event_active, ctf_only_user)
        result = ctf_instance_visibility_policy(ctf_only_user, _instances("kali", "ubuntu", "panos"))
        assert [i.os_type for i in result] == ["kali", "ubuntu"]

    def test_empty_config_shows_all(self, ctf_event_active, ctf_only_user):
        ctf_event_active.visible_os_types = []
        ctf_event_active.save(update_fields=["visible_os_types", "updated_at"])
        _enroll(ctf_event_active, ctf_only_user)
        result = ctf_instance_visibility_policy(ctf_only_user, _instances("kali", "ubuntu", "panos"))
        assert len(result) == 3

    def test_platform_users_unfiltered(self, django_user_model):
        platform_user = django_user_model.objects.create_user(
            username="plat@test.com", email="plat@test.com", is_staff=True
        )
        result = ctf_instance_visibility_policy(platform_user, _instances("kali", "ubuntu"))
        assert len(result) == 2

    def test_unenrolled_participant_falls_back_restrictive(self, ctf_only_user):
        result = ctf_instance_visibility_policy(ctf_only_user, _instances("kali", "ubuntu"))
        assert [i.os_type for i in result] == ["kali"]

    def test_resolution_failure_fails_closed(self, ctf_only_user, monkeypatch):
        def boom(_user):
            raise RuntimeError("db down")

        monkeypatch.setattr("ctf.services.range.visibility._visible_os_types_for", boom)
        result = ctf_instance_visibility_policy(ctf_only_user, _instances("kali", "ubuntu"))
        assert [i.os_type for i in result] == ["kali"]
