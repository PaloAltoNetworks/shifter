"""Tests for Range API endpoints."""

import pytest
from django.urls import reverse

from mission_control.models import AgentConfig, OperatingSystem, Range


@pytest.fixture
def windows_os(db):
    return OperatingSystem.objects.get(slug="windows")


@pytest.fixture
def test_agent(db, django_user_model, windows_os):
    user = django_user_model.objects.create_user(
        username="rangetest", email="rangetest@example.com", password="testpass"
    )
    agent = AgentConfig.objects.create(
        user=user,
        os=windows_os,
        name="Test XDR Agent",
        s3_key="agents/test/fake.msi",
        original_filename="agent.msi",
        file_size_bytes=50000000,
        sha256_hash="abc123",
    )
    return agent


@pytest.mark.django_db
class TestRangeStatus:
    def test_requires_login(self, client):
        response = client.get(reverse("mission_control:range_status"))
        assert response.status_code == 302  # Redirect to login

    def test_returns_no_range_when_none_exists(self, client, test_agent):
        client.force_login(test_agent.user)
        response = client.get(reverse("mission_control:range_status"))
        assert response.status_code == 200
        data = response.json()
        assert data["has_range"] is False
        assert data["range"] is None

    def test_returns_active_range(self, client, test_agent):
        client.force_login(test_agent.user)

        # Create an active range
        range_obj = Range.objects.create(
            user=test_agent.user,
            agent=test_agent,
            status=Range.Status.READY,
            victim_ip="10.0.1.100",
            chat_url="http://localhost:3000/chat/1",
        )

        response = client.get(reverse("mission_control:range_status"))
        assert response.status_code == 200
        data = response.json()
        assert data["has_range"] is True
        assert data["range"]["id"] == range_obj.id
        assert data["range"]["status"] == "ready"
        assert data["range"]["victim_ip"] == "10.0.1.100"


@pytest.mark.django_db
class TestLaunchRange:
    def test_requires_login(self, client):
        response = client.post(reverse("mission_control:launch_range"))
        assert response.status_code == 302

    def test_requires_agent_id(self, client, test_agent):
        client.force_login(test_agent.user)
        response = client.post(
            reverse("mission_control:launch_range"),
            data={},
            content_type="application/json",
        )
        assert response.status_code == 400
        assert "agent_id" in response.json()["error"]

    def test_rejects_nonexistent_agent(self, client, test_agent):
        client.force_login(test_agent.user)
        response = client.post(
            reverse("mission_control:launch_range"),
            data={"agent_id": 99999},
            content_type="application/json",
        )
        assert response.status_code == 404

    def test_successful_launch(self, client, test_agent, monkeypatch):
        # Mock the provisioner to avoid threading
        monkeypatch.setattr(
            "mission_control.services.provisioner.threading.Thread",
            lambda *args, **kwargs: type("MockThread", (), {"start": lambda self: None})()
        )

        client.force_login(test_agent.user)
        response = client.post(
            reverse("mission_control:launch_range"),
            data={"agent_id": test_agent.id},
            content_type="application/json",
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["range"]["status"] == "provisioning"
        assert data["range"]["agent_id"] == test_agent.id

    def test_rejects_when_range_exists(self, client, test_agent, monkeypatch):
        monkeypatch.setattr(
            "mission_control.services.provisioner.threading.Thread",
            lambda *args, **kwargs: type("MockThread", (), {"start": lambda self: None})()
        )
        client.force_login(test_agent.user)

        # Create existing range
        Range.objects.create(
            user=test_agent.user,
            agent=test_agent,
            status=Range.Status.READY,
        )

        response = client.post(
            reverse("mission_control:launch_range"),
            data={"agent_id": test_agent.id},
            content_type="application/json",
        )

        assert response.status_code == 409
        assert "already have an active range" in response.json()["error"]


@pytest.mark.django_db
class TestDestroyRange:
    def test_requires_login(self, client):
        response = client.post(reverse("mission_control:destroy_range"))
        assert response.status_code == 302

    def test_returns_404_when_no_range(self, client, test_agent):
        client.force_login(test_agent.user)
        response = client.post(reverse("mission_control:destroy_range"))
        assert response.status_code == 404

    def test_successful_destroy(self, client, test_agent, monkeypatch):
        monkeypatch.setattr(
            "mission_control.services.provisioner.threading.Thread",
            lambda *args, **kwargs: type("MockThread", (), {"start": lambda self: None})()
        )
        client.force_login(test_agent.user)

        # Create a ready range
        Range.objects.create(
            user=test_agent.user,
            agent=test_agent,
            status=Range.Status.READY,
        )

        response = client.post(reverse("mission_control:destroy_range"))
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["range"]["status"] == "destroying"


@pytest.mark.django_db
class TestListAgents:
    def test_requires_login(self, client):
        response = client.get(reverse("mission_control:list_agents"))
        assert response.status_code == 302

    def test_returns_user_agents(self, client, test_agent):
        client.force_login(test_agent.user)
        response = client.get(reverse("mission_control:list_agents"))

        assert response.status_code == 200
        data = response.json()
        assert len(data["agents"]) == 1
        assert data["agents"][0]["id"] == test_agent.id
        assert data["agents"][0]["name"] == "Test XDR Agent"


@pytest.mark.django_db
class TestRangeCallback:
    def test_missing_fields(self, client, test_agent):
        response = client.post(
            reverse("mission_control:range_callback"),
            data={"range_id": 1},
            content_type="application/json",
        )
        assert response.status_code == 400
        assert "Missing required fields" in response.json()["error"]

    def test_invalid_token(self, client, test_agent):
        range_obj = Range.objects.create(
            user=test_agent.user,
            agent=test_agent,
            status=Range.Status.PROVISIONING,
        )
        response = client.post(
            reverse("mission_control:range_callback"),
            data={
                "range_id": range_obj.id,
                "status": "ready",
                "callback_token": "invalid_token",
            },
            content_type="application/json",
        )
        assert response.status_code == 403
        assert "Invalid callback token" in response.json()["error"]

    def test_valid_ready_callback(self, client, test_agent):
        from mission_control.services.provisioner import _generate_callback_token

        range_obj = Range.objects.create(
            user=test_agent.user,
            agent=test_agent,
            status=Range.Status.PROVISIONING,
        )
        token = _generate_callback_token(range_obj.id)

        response = client.post(
            reverse("mission_control:range_callback"),
            data={
                "range_id": range_obj.id,
                "status": "ready",
                "callback_token": token,
                "victim_ip": "10.0.1.50",
                "chat_url": "http://localhost:3000/chat/test",
            },
            content_type="application/json",
        )
        assert response.status_code == 200

        range_obj.refresh_from_db()
        assert range_obj.status == Range.Status.READY
        assert range_obj.victim_ip == "10.0.1.50"
        assert range_obj.chat_url == "http://localhost:3000/chat/test"

    def test_rejects_invalid_state_transition(self, client, test_agent):
        """Callback should reject transitions from unexpected states (replay protection)."""
        from mission_control.services.provisioner import _generate_callback_token

        # Create a range that's already READY
        range_obj = Range.objects.create(
            user=test_agent.user,
            agent=test_agent,
            status=Range.Status.READY,
        )
        token = _generate_callback_token(range_obj.id)

        # Try to transition to READY again (replay attack)
        response = client.post(
            reverse("mission_control:range_callback"),
            data={
                "range_id": range_obj.id,
                "status": "ready",
                "callback_token": token,
            },
            content_type="application/json",
        )
        assert response.status_code == 409
        assert "Invalid state transition" in response.json()["error"]

    def test_destroyed_callback_requires_destroying_state(self, client, test_agent):
        """destroyed callback only valid when range is in DESTROYING state."""
        from mission_control.services.provisioner import _generate_callback_token

        # Range is READY, not DESTROYING
        range_obj = Range.objects.create(
            user=test_agent.user,
            agent=test_agent,
            status=Range.Status.READY,
        )
        token = _generate_callback_token(range_obj.id)

        response = client.post(
            reverse("mission_control:range_callback"),
            data={
                "range_id": range_obj.id,
                "status": "destroyed",
                "callback_token": token,
            },
            content_type="application/json",
        )
        assert response.status_code == 409

    def test_valid_destroyed_callback(self, client, test_agent):
        from mission_control.services.provisioner import _generate_callback_token

        range_obj = Range.objects.create(
            user=test_agent.user,
            agent=test_agent,
            status=Range.Status.DESTROYING,
        )
        token = _generate_callback_token(range_obj.id)

        response = client.post(
            reverse("mission_control:range_callback"),
            data={
                "range_id": range_obj.id,
                "status": "destroyed",
                "callback_token": token,
            },
            content_type="application/json",
        )
        assert response.status_code == 200

        range_obj.refresh_from_db()
        assert range_obj.status == Range.Status.DESTROYED
        assert range_obj.destroyed_at is not None
