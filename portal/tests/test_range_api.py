"""Tests for Range API endpoints."""

from unittest.mock import patch

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


@pytest.fixture
def mock_provisioner():
    """Mock the provisioner service to avoid AWS calls."""
    with patch("mission_control.services.provisioner.start_provisioning") as mock_provision, \
         patch("mission_control.services.provisioner.start_teardown") as mock_teardown:
        mock_provision.return_value = None  # No ARN in test mode
        mock_teardown.return_value = None
        yield {"provision": mock_provision, "teardown": mock_teardown}


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
            victim_ip="10.0.1.100",  # Stored in DB but not exposed to client
            chat_url="http://localhost:3000/chat/1",
        )

        response = client.get(reverse("mission_control:range_status"))
        assert response.status_code == 200
        data = response.json()
        assert data["has_range"] is True
        assert data["range"]["id"] == range_obj.id
        assert data["range"]["status"] == "ready"
        assert data["range"]["chat_url"] == "http://localhost:3000/chat/1"
        # victim_ip intentionally not exposed to client (internal infra detail)
        assert "victim_ip" not in data["range"]


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

    def test_successful_launch(self, client, test_agent, settings):
        # Ensure Step Functions ARN is not set (local dev mode)
        settings.PROVISION_STATE_MACHINE_ARN = ""

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

    def test_successful_launch_with_step_functions(self, client, test_agent):
        """Test launch with mocked Step Functions."""
        with patch("mission_control.services.provisioner._get_sfn_client") as mock_client:
            mock_client.return_value.start_execution.return_value = {
                "executionArn": "arn:aws:states:us-east-2:123:execution:test:abc"
            }

            client.force_login(test_agent.user)
            with patch.object(
                client.session, "get", return_value=None
            ):
                # Need to patch settings for this test
                from django.conf import settings
                original_arn = getattr(settings, "PROVISION_STATE_MACHINE_ARN", "")
                settings.PROVISION_STATE_MACHINE_ARN = "arn:aws:states:us-east-2:123:stateMachine:test"

                try:
                    response = client.post(
                        reverse("mission_control:launch_range"),
                        data={"agent_id": test_agent.id},
                        content_type="application/json",
                    )

                    assert response.status_code == 200
                    data = response.json()
                    assert data["success"] is True
                    assert data["range"]["status"] == "provisioning"

                    # Verify execution ARN was stored
                    range_obj = Range.objects.get(id=data["range"]["id"])
                    assert range_obj.step_function_execution_arn == "arn:aws:states:us-east-2:123:execution:test:abc"
                finally:
                    settings.PROVISION_STATE_MACHINE_ARN = original_arn

    def test_rejects_when_range_exists(self, client, test_agent, settings):
        settings.PROVISION_STATE_MACHINE_ARN = ""
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
class TestCancelRange:
    def test_requires_login(self, client):
        response = client.post(reverse("mission_control:cancel_range"))
        assert response.status_code == 302

    def test_returns_404_when_no_range(self, client, test_agent):
        client.force_login(test_agent.user)
        response = client.post(reverse("mission_control:cancel_range"))
        assert response.status_code == 404

    def test_successful_cancel_provisioning(self, client, test_agent):
        client.force_login(test_agent.user)

        # Create a provisioning range
        range_obj = Range.objects.create(
            user=test_agent.user,
            agent=test_agent,
            status=Range.Status.PROVISIONING,
        )

        response = client.post(reverse("mission_control:cancel_range"))
        assert response.status_code == 200
        assert response.json()["success"] is True

        range_obj.refresh_from_db()
        assert range_obj.status == Range.Status.DESTROYED
        assert range_obj.destroyed_at is not None

    def test_cannot_cancel_ready_range(self, client, test_agent):
        client.force_login(test_agent.user)

        # Create a ready range (can't cancel, must destroy)
        Range.objects.create(
            user=test_agent.user,
            agent=test_agent,
            status=Range.Status.READY,
        )

        response = client.post(reverse("mission_control:cancel_range"))
        assert response.status_code == 400
        assert "Cannot cancel" in response.json()["error"]


@pytest.mark.django_db
class TestDestroyRange:
    def test_requires_login(self, client):
        response = client.post(reverse("mission_control:destroy_range"))
        assert response.status_code == 302

    def test_returns_404_when_no_range(self, client, test_agent):
        client.force_login(test_agent.user)
        response = client.post(reverse("mission_control:destroy_range"))
        assert response.status_code == 404

    def test_successful_destroy(self, client, test_agent, settings):
        settings.TEARDOWN_STATE_MACHINE_ARN = ""
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

    def test_can_destroy_failed_range(self, client, test_agent, settings):
        """Failed ranges can be destroyed to clean up."""
        settings.TEARDOWN_STATE_MACHINE_ARN = ""
        client.force_login(test_agent.user)

        # Create a failed range
        Range.objects.create(
            user=test_agent.user,
            agent=test_agent,
            status=Range.Status.FAILED,
            error_message="Provisioning timed out",
        )

        response = client.post(reverse("mission_control:destroy_range"))
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["range"]["status"] == "destroying"


@pytest.mark.django_db
class TestLaunchRangeWhileDestroying:
    """Test that users cannot launch while a range is being destroyed."""

    def test_cannot_launch_while_destroying(self, client, test_agent, settings):
        settings.PROVISION_STATE_MACHINE_ARN = ""
        client.force_login(test_agent.user)

        # Create a range being destroyed
        Range.objects.create(
            user=test_agent.user,
            agent=test_agent,
            status=Range.Status.DESTROYING,
        )

        # Try to launch a new range
        response = client.post(
            reverse("mission_control:launch_range"),
            data={"agent_id": test_agent.id},
            content_type="application/json",
        )

        assert response.status_code == 409
        assert "already have an active range" in response.json()["error"]


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
class TestSubnetIndexAllocation:
    """Tests for subnet_index allocation in Range model."""

    def test_allocates_index_on_launch(self, client, test_agent, settings):
        """Launch should allocate a subnet_index."""
        settings.PROVISION_STATE_MACHINE_ARN = ""
        client.force_login(test_agent.user)

        response = client.post(
            reverse("mission_control:launch_range"),
            data={"agent_id": test_agent.id},
            content_type="application/json",
        )

        assert response.status_code == 200
        range_obj = Range.objects.get(id=response.json()["range"]["id"])
        assert range_obj.subnet_index is not None
        assert 1 <= range_obj.subnet_index <= 254

    def test_first_allocation_returns_one(self, test_agent):
        """First allocation should return index 1."""
        index = Range.allocate_subnet_index()
        assert index == 1

    def test_allocates_sequential_indices(self, test_agent):
        """Allocations should fill gaps."""
        # Create range with index 1
        Range.objects.create(
            user=test_agent.user,
            agent=test_agent,
            status=Range.Status.PROVISIONING,
            subnet_index=1,
        )

        # Next allocation should be 2
        index = Range.allocate_subnet_index()
        assert index == 2

    def test_reuses_destroyed_indices(self, test_agent):
        """Destroyed ranges should free up their indices."""
        # Create and destroy a range with index 1
        Range.objects.create(
            user=test_agent.user,
            agent=test_agent,
            status=Range.Status.DESTROYED,
            subnet_index=1,
        )

        # Should reuse index 1
        index = Range.allocate_subnet_index()
        assert index == 1

    def test_fills_gaps(self, test_agent):
        """Should fill gaps in index sequence."""
        # Create ranges with indices 1 and 3 (gap at 2)
        Range.objects.create(
            user=test_agent.user,
            agent=test_agent,
            status=Range.Status.READY,
            subnet_index=1,
        )
        Range.objects.create(
            user=test_agent.user,
            agent=test_agent,
            status=Range.Status.READY,
            subnet_index=3,
        )

        # Should fill gap at index 2
        index = Range.allocate_subnet_index()
        assert index == 2

    def test_skips_active_indices(self, test_agent):
        """Should not reuse indices from non-destroyed ranges."""
        # Create ranges in various active states
        for i, status in enumerate([
            Range.Status.PROVISIONING,
            Range.Status.READY,
            Range.Status.PAUSED,
            Range.Status.DESTROYING,
            Range.Status.FAILED,
        ], start=1):
            Range.objects.create(
                user=test_agent.user,
                agent=test_agent,
                status=status,
                subnet_index=i,
            )

        # Next allocation should be 6
        index = Range.allocate_subnet_index()
        assert index == 6

    def test_raises_when_exhausted(self, test_agent):
        """Should raise ValueError when all indices are used."""
        # Create ranges for all 254 indices
        for i in range(1, 255):
            Range.objects.create(
                user=test_agent.user,
                agent=test_agent,
                status=Range.Status.READY,
                subnet_index=i,
            )

        with pytest.raises(ValueError, match="No subnet indices available"):
            Range.allocate_subnet_index()

    def test_capacity_error_returns_503(self, client, test_agent, settings, django_user_model):
        """API should return 503 when no capacity available."""
        settings.PROVISION_STATE_MACHINE_ARN = ""
        client.force_login(test_agent.user)

        # Create a different user to hold the 254 ranges (so test_agent.user has no active range)
        other_user = django_user_model.objects.create_user(
            username="capacitytest", email="capacitytest@example.com", password="testpass"
        )

        # Create ranges for all 254 indices (owned by other_user, all DESTROYED so they don't block)
        # Actually we need ACTIVE ranges to block the indices
        for i in range(1, 255):
            Range.objects.create(
                user=other_user,
                agent=test_agent,
                status=Range.Status.READY,
                subnet_index=i,
            )

        response = client.post(
            reverse("mission_control:launch_range"),
            data={"agent_id": test_agent.id},
            content_type="application/json",
        )

        assert response.status_code == 503
        assert "No capacity available" in response.json()["error"]
