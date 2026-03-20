"""Tests for organizer ownership checks on all CTF admin views.

Verifies that organizer views and APIs return 403 when an organizer
attempts to access an event they do not own.
"""

from __future__ import annotations

import pytest
from django.urls import reverse


@pytest.mark.django_db
class TestAdminViewOwnershipChecks:
    """Verify HTML admin views reject non-owning organizers with 403."""

    def test_range_list_denies_other_organizer(self, client, ctf_event, second_organizer_user):
        client.force_login(second_organizer_user)
        url = reverse("ctf:admin_range_list", kwargs={"event_id": ctf_event.id})
        assert client.get(url).status_code == 403

    def test_notification_list_denies_other_organizer(self, client, ctf_event, second_organizer_user):
        client.force_login(second_organizer_user)
        url = reverse("ctf:admin_notification_list", kwargs={"event_id": ctf_event.id})
        assert client.get(url).status_code == 403

    def test_notification_create_denies_other_organizer(self, client, ctf_event, second_organizer_user):
        client.force_login(second_organizer_user)
        url = reverse("ctf:admin_notification_create", kwargs={"event_id": ctf_event.id})
        assert client.get(url).status_code == 403

    def test_team_list_denies_other_organizer(self, client, ctf_event, second_organizer_user):
        client.force_login(second_organizer_user)
        url = reverse("ctf:admin_team_list", kwargs={"event_id": ctf_event.id})
        assert client.get(url).status_code == 403

    def test_scoreboard_denies_other_organizer(self, client, ctf_event, second_organizer_user):
        client.force_login(second_organizer_user)
        url = reverse("ctf:admin_scoreboard", kwargs={"event_id": ctf_event.id})
        assert client.get(url).status_code == 403

    def test_analytics_denies_other_organizer(self, client, ctf_event, second_organizer_user):
        client.force_login(second_organizer_user)
        url = reverse("ctf:admin_analytics", kwargs={"event_id": ctf_event.id})
        assert client.get(url).status_code == 403


@pytest.mark.django_db
class TestAPIOwnershipChecks:
    """Verify API endpoints reject non-owning organizers with 403."""

    def test_api_event_detail_denies_other_organizer(self, client, ctf_event, second_organizer_user):
        client.force_login(second_organizer_user)
        url = reverse("ctf:api_event_detail", kwargs={"event_id": ctf_event.id})
        response = client.get(url)
        assert response.status_code == 403

    def test_api_notification_list_denies_other_organizer(self, client, ctf_event, second_organizer_user):
        client.force_login(second_organizer_user)
        url = reverse("ctf:api_notification_list", kwargs={"event_id": ctf_event.id})
        response = client.get(url)
        assert response.status_code == 403

    def test_api_notification_send_denies_other_organizer(
        self, client, ctf_event, second_organizer_user, organizer_user
    ):
        from ctf.enums import NotificationStatus, NotificationType
        from ctf.models import CTFNotification

        notif = CTFNotification.objects.create(
            event=ctf_event,
            notification_type=NotificationType.ANNOUNCEMENT.value,
            subject="Test",
            body="Body",
            status=NotificationStatus.DRAFT.value,
            recipient_filter="participants",
            created_by=organizer_user,
        )

        client.force_login(second_organizer_user)
        url = reverse("ctf:api_notification_send", kwargs={"notification_id": notif.id})
        response = client.post(url)
        assert response.status_code == 403

    def test_api_range_list_denies_other_organizer(self, client, ctf_event, second_organizer_user):
        client.force_login(second_organizer_user)
        url = reverse("ctf:api_range_list", kwargs={"event_id": ctf_event.id})
        response = client.get(url)
        assert response.status_code == 403

    def test_api_provision_ranges_denies_other_organizer(self, client, ctf_event, second_organizer_user):
        client.force_login(second_organizer_user)
        url = reverse("ctf:api_provision_ranges", kwargs={"event_id": ctf_event.id})
        response = client.post(url)
        assert response.status_code == 403


@pytest.mark.django_db
class TestOwnerCanAccess:
    """Verify the owning organizer CAN access these views (not just that others can't)."""

    def test_range_list_allows_owner(self, authenticated_organizer_client, ctf_event):
        url = reverse("ctf:admin_range_list", kwargs={"event_id": ctf_event.id})
        assert authenticated_organizer_client.get(url).status_code == 200

    def test_notification_list_allows_owner(self, authenticated_organizer_client, ctf_event):
        url = reverse("ctf:admin_notification_list", kwargs={"event_id": ctf_event.id})
        assert authenticated_organizer_client.get(url).status_code == 200

    def test_notification_create_allows_owner(self, authenticated_organizer_client, ctf_event):
        url = reverse("ctf:admin_notification_create", kwargs={"event_id": ctf_event.id})
        assert authenticated_organizer_client.get(url).status_code == 200

    def test_api_range_list_allows_owner(self, authenticated_organizer_client, ctf_event):
        url = reverse("ctf:api_range_list", kwargs={"event_id": ctf_event.id})
        assert authenticated_organizer_client.get(url).status_code == 200

    def test_api_notification_list_allows_owner(self, authenticated_organizer_client, ctf_event):
        url = reverse("ctf:api_notification_list", kwargs={"event_id": ctf_event.id})
        assert authenticated_organizer_client.get(url).status_code == 200
